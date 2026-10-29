"""Shared HTTP fetching with robots.txt checks, retries, and polite pacing."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

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
        session: requests.Session | None = None,
        user_agent: str = USER_AGENT,
        delay: float = REQUEST_DELAY_SECONDS,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.respect_robots = respect_robots
        self.stop_event = stop_event
        self.user_agent = user_agent
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
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
        except requests.RequestException as exc:
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
            elapsed = time.monotonic() - self._last_request.get(domain, 0)
            remaining = self.delay - elapsed
            if remaining <= 0:
                self._last_request[domain] = time.monotonic()
                return

        if self.stop_event:
            self.stop_event.wait(timeout=remaining)
        else:
            time.sleep(remaining)

        with self._lock:
            self._last_request[domain] = time.monotonic()

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
        last_error: requests.RequestException | None = None

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
            except requests.RequestException as exc:
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
