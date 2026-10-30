"""Shared HTTP fetching with robots.txt checks, retries, and polite pacing."""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    cffi_requests = None
    HAS_CURL_CFFI = False

try:
    from .config import (
        HTML_CONTENT_TYPES,
        REQUEST_DELAY_SECONDS,
        REQUEST_TIMEOUT,
        RETRY_DELAY_SECONDS,
        USER_AGENT,
    )
except ImportError:  # pragma: no cover - direct script execution
    from config import (
        HTML_CONTENT_TYPES,
        REQUEST_DELAY_SECONDS,
        REQUEST_TIMEOUT,
        RETRY_DELAY_SECONDS,
        USER_AGENT,
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

    def __init__(self, message: str, url: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class RobotsDisallowed(FetchError):
    """The target URL is disallowed by robots.txt."""


class NonHtmlContent(FetchError):
    """The server returned a non-HTML content type."""


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    html: str
    status_code: int
    content_type: str


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
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.respect_robots = respect_robots
        self.stop_event = stop_event
        self.user_agent = user_agent
        self.delay = delay
        self.impersonate = impersonate
        self.proxy = proxy
        self.rotate_user_agent = rotate_user_agent

        if session is not None:
            self.session = session
            self.is_curl_cffi = False
        elif impersonate and HAS_CURL_CFFI:
            target_imp = "chrome" if impersonate is True else str(impersonate)
            try:
                self.session = cffi_requests.Session(impersonate=target_imp)
                self.is_curl_cffi = True
            except Exception as exc:
                self.logger.warning("Failed to initialize curl_cffi with impersonate='%s': %s", target_imp, exc)
                self.session = requests.Session()
                self.is_curl_cffi = False
        else:
            self.session = requests.Session()
            self.is_curl_cffi = False

        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        self.session.headers.update(DEFAULT_BROWSER_HEADERS)
        self.session.headers["User-Agent"] = self.user_agent
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    # --- robots.txt ---

    def _robots_for(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            if origin in self._robots:
                return self._robots[origin]

        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            response = self.session.get(f"{origin}/robots.txt", timeout=REQUEST_TIMEOUT, allow_redirects=True)
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
        return parser

    def can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        return self._robots_for(url).can_fetch(self.user_agent, url)

    # --- politeness ---

    def _wait_for_domain(self, domain: str) -> None:
        with self._lock:
            now = time.monotonic()
            next_allowed = max(self._last_request.get(domain, 0.0), now)
            self._last_request[domain] = next_allowed + self.delay
            wait_time = next_allowed - now

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

    # --- fetching ---

    def fetch(self, url: str) -> FetchResult:
        if self.stop_event and self.stop_event.is_set():
            raise FetchError("Crawl stopped by request", url)

        if not self.can_fetch(url):
            raise RobotsDisallowed("Disallowed by robots.txt", url)

        domain = urlparse(url).netloc.lower()
        last_error: Exception | None = None

        if self.rotate_user_agent:
            ua = random.choice(USER_AGENTS)
            self.session.headers["User-Agent"] = ua

        for attempt in range(2):
            if self.stop_event and self.stop_event.is_set():
                raise FetchError("Crawl stopped by request", url)
            self._wait_for_domain(domain)
            if self.stop_event and self.stop_event.is_set():
                raise FetchError("Crawl stopped by request", url)

            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type and content_type not in HTML_CONTENT_TYPES:
                    self.logger.info("Skipped non-HTML resource %s (%s)", url, content_type)
                    raise NonHtmlContent(f"Non-HTML content type: {content_type}", url, response.status_code)
                return FetchResult(
                    requested_url=url,
                    final_url=getattr(response, "url", url) or url,
                    html=response.text,
                    status_code=response.status_code,
                    content_type=content_type,
                )
            except NonHtmlContent:
                raise
            except Exception as exc:
                last_error = exc
                if self.stop_event and self.stop_event.is_set():
                    raise FetchError("Crawl stopped by request", url) from exc
                if attempt == 0:
                    self.logger.warning("Request failed for %s; retrying: %s", url, exc)
                    self._sleep(RETRY_DELAY_SECONDS)

        status_code = getattr(getattr(last_error, "response", None), "status_code", None)
        raise FetchError(f"Request failed for {url}: {last_error}", url, status_code) from last_error

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
