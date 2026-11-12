"""Shared HTTP fetching with robots.txt checks, retries, and polite pacing."""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    cffi_requests = None
    HAS_CURL_CFFI = False

try:
    from .config import (
        DEFAULT_BACKOFF_BASE,
        DEFAULT_BACKOFF_MAX,
        DEFAULT_CIRCUIT_COOLDOWN,
        DEFAULT_CIRCUIT_THRESHOLD,
        DEFAULT_MAX_RETRIES,
        HTML_CONTENT_TYPES,
        REQUEST_DELAY_SECONDS,
        REQUEST_TIMEOUT,
        USER_AGENT,
    )
    from .retry import (
        CATEGORY_CIRCUIT_OPEN,
        CATEGORY_NON_HTML,
        CATEGORY_ROBOTS,
        CATEGORY_STOPPED,
        CATEGORY_UNKNOWN,
        RETRYABLE_CATEGORIES,
        AdaptiveRateLimiter,
        DomainCircuitBreaker,
        RetryPolicy,
        classify_error,
    )
except ImportError:  # pragma: no cover - direct script execution
    from config import (
        DEFAULT_BACKOFF_BASE,
        DEFAULT_BACKOFF_MAX,
        DEFAULT_CIRCUIT_COOLDOWN,
        DEFAULT_CIRCUIT_THRESHOLD,
        DEFAULT_MAX_RETRIES,
        HTML_CONTENT_TYPES,
        REQUEST_DELAY_SECONDS,
        REQUEST_TIMEOUT,
        USER_AGENT,
    )
    from retry import (
        CATEGORY_CIRCUIT_OPEN,
        CATEGORY_NON_HTML,
        CATEGORY_ROBOTS,
        CATEGORY_STOPPED,
        CATEGORY_UNKNOWN,
        RETRYABLE_CATEGORIES,
        AdaptiveRateLimiter,
        DomainCircuitBreaker,
        RetryPolicy,
        classify_error,
    )

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

DEFAULT_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-CH-UA": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class FetchError(Exception):
    """Base error for a failed fetch."""

    def __init__(
        self,
        message: str,
        url: str = "",
        status_code: int | None = None,
        error_type: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.error_type = error_type or classify_error(self, status_code)
        self.retry_after = retry_after


class RobotsDisallowed(FetchError):
    """The target URL is disallowed by robots.txt."""

    def __init__(self, message: str, url: str = "", status_code: int | None = None) -> None:
        super().__init__(message, url, status_code, error_type=CATEGORY_ROBOTS)


class NonHtmlContent(FetchError):
    """The server returned a non-HTML content type."""

    def __init__(self, message: str, url: str = "", status_code: int | None = None) -> None:
        super().__init__(message, url, status_code, error_type=CATEGORY_NON_HTML)


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    html: str
    status_code: int
    content_type: str
    etag: str = ""
    last_modified: str = ""
    content_hash: str = ""
    not_modified: bool = False


def _parse_retry_after(value: Any) -> float | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when is not None:
            now = datetime.now(tz=when.tzinfo or timezone.utc)
            return max(0.0, (when - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _content_hash(response: Any, text: str) -> str:
    body = getattr(response, "content", None)
    if isinstance(body, (bytes, bytearray)) and body:
        return hashlib.sha256(bytes(body)).hexdigest()
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


class Fetcher:
    """Fetch HTML pages while respecting robots.txt and per-domain politeness."""

    def __init__(
        self,
        logger: logging.Logger | None = None,
        respect_robots: bool = True,
        stop_event: threading.Event | None = None,
        session: Any = None,
        user_agent: str = USER_AGENT,
        delay: float = REQUEST_DELAY_SECONDS,
        impersonate: str | bool | None = None,
        proxy: str | None = None,
        rotate_user_agent: bool = False,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
        circuit_threshold: int = DEFAULT_CIRCUIT_THRESHOLD,
        circuit_cooldown: float = DEFAULT_CIRCUIT_COOLDOWN,
        cache: Any = None,
        conditional: bool = False,
        adaptive_rate_limit: bool = True,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.respect_robots = respect_robots
        self.stop_event = stop_event
        self.user_agent = user_agent
        self.delay = delay
        self.impersonate = impersonate
        self.proxy = proxy
        self.rotate_user_agent = rotate_user_agent
        self.max_retries = max(0, int(max_retries))
        self.retry_policy = RetryPolicy(
            max_attempts=self.max_retries + 1,
            base_delay=max(0.0, float(backoff_base)),
            max_delay=max(0.1, float(backoff_max)),
        )
        self.circuit = DomainCircuitBreaker(
            failure_threshold=circuit_threshold,
            cooldown=circuit_cooldown,
        )
        self.adaptive_rate_limit = bool(adaptive_rate_limit)
        self.rate_limiter = (
            AdaptiveRateLimiter(self.delay, max_delay=max(1.0, float(backoff_max)))
            if self.adaptive_rate_limit
            else None
        )
        self.cache = cache
        self.conditional = bool(conditional and cache is not None)
        self._custom_session = session
        self._thread_local = threading.local()
        self.is_curl_cffi = bool(impersonate and HAS_CURL_CFFI)
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._active_sessions: list[Any] = []
        # Re-entrant: helpers called while a lock is held (e.g. _get_session from
        # _robots_for) must not be able to deadlock the calling thread.
        self._lock = threading.RLock()

    @property
    def session(self) -> Any:
        return self._get_session()

    def _get_session(self) -> Any:
        if self._custom_session is not None:
            return self._custom_session

        sess = getattr(self._thread_local, "session", None)
        if sess is not None:
            return sess

        if self.impersonate and HAS_CURL_CFFI:
            target_imp = "chrome" if self.impersonate is True else str(self.impersonate)
            try:
                sess = cffi_requests.Session(impersonate=target_imp)
            except Exception as exc:
                self.logger.warning("Failed to initialize curl_cffi with impersonate='%s': %s", target_imp, exc)
                sess = requests.Session()
                if hasattr(sess, "mount"):
                    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=1)
                    sess.mount("https://", adapter)
                    sess.mount("http://", adapter)
        else:
            sess = requests.Session()
            if hasattr(sess, "mount"):
                adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=1)
                sess.mount("https://", adapter)
                sess.mount("http://", adapter)

        if self.proxy:
            sess.proxies = {"http": self.proxy, "https": self.proxy}

        sess.headers.update(DEFAULT_BROWSER_HEADERS)
        sess.headers["User-Agent"] = self.user_agent
        self._thread_local.session = sess
        with self._lock:
            self._active_sessions.append(sess)
        return sess

    # --- robots.txt ---

    def _robots_for(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        with self._lock:
            cached = self._robots.get(origin)
            if cached is not None:
                return cached
            # One lock per origin: concurrent workers for the same site wait for a
            # single robots.txt fetch instead of issuing duplicate requests.
            origin_lock = self._robots_locks.setdefault(origin, threading.Lock())

        with origin_lock:
            # Another thread may have populated the cache while we waited.
            with self._lock:
                cached = self._robots.get(origin)
                if cached is not None:
                    return cached

            parser = RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            # Fetch outside the shared lock so a slow robots.txt for one origin
            # never blocks workers on other origins.
            session = self._get_session()
            try:
                response = session.get(f"{origin}/robots.txt", timeout=REQUEST_TIMEOUT, allow_redirects=True)
                if response.status_code >= 400:
                    parser.parse([])
                else:
                    parser.parse(response.text.splitlines())
            except Exception as exc:
                # An unreachable robots.txt means "no restrictions".
                self.logger.warning("Could not read robots.txt for %s: %s", origin, exc)
                parser.parse([])

            with self._lock:
                self._robots[origin] = parser
                self._robots_locks.pop(origin, None)
            return parser

    def can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        return self._robots_for(url).can_fetch(self.user_agent, url)

    # --- politeness / adaptive pacing ---

    def _wait_for_domain(self, domain: str) -> None:
        effective_delay = (
            self.rate_limiter.delay_for(domain) if self.rate_limiter is not None else self.delay
        )
        if effective_delay <= 0 or (self.stop_event and self.stop_event.is_set()):
            return
        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            target = max(now, last + effective_delay)
            wait_time = target - now
            self._last_request[domain] = target

        if wait_time > 0:
            if self.stop_event:
                self.stop_event.wait(timeout=wait_time)
            else:
                time.sleep(wait_time)

    def _sleep(self, seconds: float) -> None:
        if self.stop_event:
            self.stop_event.wait(timeout=seconds)
        else:
            time.sleep(seconds)

    def _conditional_headers(self, url: str) -> dict[str, str]:
        if not self.conditional or self.cache is None:
            return {}
        if hasattr(self.cache, "conditional_headers"):
            try:
                return dict(self.cache.conditional_headers(url) or {})
            except Exception:
                return {}
        cached = self.cache.cache_get(url) if hasattr(self.cache, "cache_get") else None
        if not cached:
            return {}
        headers: dict[str, str] = {}
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = str(cached["last_modified"])
        return headers

    def _cached_record(self, url: str) -> dict[str, Any]:
        if self.cache is None:
            return {}
        try:
            if hasattr(self.cache, "get"):
                return dict(self.cache.get(url) or {})
            if hasattr(self.cache, "cache_get"):
                return dict(self.cache.cache_get(url) or {})
        except Exception:
            return {}
        return {}

    # --- fetching ---

    def fetch(self, url: str) -> FetchResult:
        if self.stop_event and self.stop_event.is_set():
            raise FetchError("Crawl stopped by request", url, error_type=CATEGORY_STOPPED)

        if not self.can_fetch(url):
            raise RobotsDisallowed("Disallowed by robots.txt", url)

        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not self.circuit.allow(domain):
            remaining = self.circuit.retry_after(domain)
            raise FetchError(
                f"Circuit breaker open for {domain}; retry in ~{max(1, int(remaining))}s",
                url,
                error_type=CATEGORY_CIRCUIT_OPEN,
                retry_after=remaining,
            )

        request_headers: dict[str, str] = {}
        if self.rotate_user_agent:
            request_headers["User-Agent"] = random.choice(USER_AGENTS)
        request_headers.update(self._conditional_headers(url))

        total_attempts = self.max_retries + 1
        last_error: Exception | None = None
        last_status: int | None = None
        last_category = "unknown"

        def _backoff(category: str, attempt: int, retry_after: float | None = None) -> None:
            if self.rate_limiter is not None:
                self.rate_limiter.record_throttle(domain, retry_after)
            delay = self.retry_policy.next_delay(attempt, retry_after)
            self.logger.warning(
                "%s for %s (%s); retrying in %.1fs", "Request failed", url, category, delay
            )
            self._sleep(delay)

        for attempt in range(1, total_attempts + 1):
            if self.stop_event and self.stop_event.is_set():
                raise FetchError("Crawl stopped by request", url, error_type=CATEGORY_STOPPED)

            self._wait_for_domain(domain)
            if self.stop_event and self.stop_event.is_set():
                raise FetchError("Crawl stopped by request", url, error_type=CATEGORY_STOPPED)

            try:
                get_kwargs: dict[str, Any] = {"timeout": REQUEST_TIMEOUT, "allow_redirects": True}
                if request_headers:
                    get_kwargs["headers"] = request_headers
                response = self.session.get(url, **get_kwargs)
            except Exception as exc:
                last_error = exc
                last_category = classify_error(exc)
                if self.stop_event and self.stop_event.is_set():
                    raise FetchError("Crawl stopped by request", url, error_type=CATEGORY_STOPPED) from exc
                self.circuit.record_failure(domain)
                if not self.circuit.allow(domain):
                    self.logger.warning("Circuit breaker opened for %s after repeated failures", domain)
                if not self.retry_policy.should_retry(last_category, attempt):
                    raise FetchError(
                        f"Request failed for {url}: {exc}",
                        url,
                        error_type=last_category,
                    ) from exc
                _backoff(last_category, attempt)
                continue

            try:
                status_code = int(getattr(response, "status_code", 200) or 200)
            except (TypeError, ValueError):
                status_code = 200
            last_status = status_code

            if status_code == 304:
                self.circuit.record_success(domain)
                if self.rate_limiter is not None:
                    self.rate_limiter.record_success(domain)
                cached = self._cached_record(url)
                return FetchResult(
                    requested_url=url,
                    final_url=getattr(response, "url", url) or url,
                    html="",
                    status_code=304,
                    content_type="text/html",
                    etag=str(cached.get("etag", "")),
                    last_modified=str(cached.get("last_modified", "")),
                    content_hash=str(cached.get("content_hash", "")),
                    not_modified=True,
                )

            if status_code >= 400:
                category = classify_error(None, status_code)
                last_category = category
                retry_after = _parse_retry_after(getattr(response, "headers", {}).get("Retry-After"))
                self.circuit.record_failure(domain)
                if not self.circuit.allow(domain):
                    self.logger.warning("Circuit breaker opened for %s after HTTP %s", domain, status_code)
                if self.retry_policy.should_retry(category, attempt):
                    _backoff(category, attempt, retry_after)
                    continue
                raise FetchError(
                    f"Request failed for {url}: HTTP {status_code}",
                    url,
                    status_code=status_code,
                    error_type=category,
                    retry_after=retry_after,
                )

            content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).split(";", 1)[0].lower()
            if content_type and content_type not in HTML_CONTENT_TYPES:
                self.logger.info("Skipped non-HTML resource %s (%s)", url, content_type)
                self.circuit.record_success(domain)
                if self.rate_limiter is not None:
                    self.rate_limiter.record_success(domain)
                raise NonHtmlContent(f"Non-HTML content type: {content_type}", url, status_code)

            text = str(getattr(response, "text", "") or "")
            self.circuit.record_success(domain)
            if self.rate_limiter is not None:
                self.rate_limiter.record_success(domain)
            headers = getattr(response, "headers", {}) or {}
            return FetchResult(
                requested_url=url,
                final_url=getattr(response, "url", url) or url,
                html=text,
                status_code=status_code,
                content_type=content_type,
                etag=str(headers.get("ETag", "") or ""),
                last_modified=str(headers.get("Last-Modified", "") or ""),
                content_hash=_content_hash(response, text),
            )

        raise FetchError(
            f"Request failed for {url}: {last_error}",
            url,
            last_status,
            error_type=last_category,
        ) from last_error

    def close(self) -> None:
        try:
            if self._custom_session is not None and hasattr(self._custom_session, "close"):
                self._custom_session.close()
            with self._lock:
                for sess in self._active_sessions:
                    try:
                        if hasattr(sess, "close"):
                            sess.close()
                    except Exception:
                        pass
                self._active_sessions.clear()
            local_sess = getattr(self._thread_local, "session", None)
            if local_sess is not None and hasattr(local_sess, "close"):
                local_sess.close()
        except Exception:
            pass
