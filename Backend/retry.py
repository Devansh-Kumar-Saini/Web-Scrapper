"""Local retry policy, error classification, and per-domain circuit breaking.

Everything in this module is dependency-free and works entirely offline.  It is
the resilience layer used by the persistent crawl queue: failures are grouped
into stable categories, retried with exponential backoff, and domains that keep
failing are temporarily short-circuited so the crawler can move on.
"""

from __future__ import annotations

import math
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# --- error categories -------------------------------------------------------

CATEGORY_DNS = "dns"
CATEGORY_CONNECTION = "connection"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_TLS = "tls"
CATEGORY_HTTP_401 = "http_401"
CATEGORY_HTTP_403 = "http_403"
CATEGORY_HTTP_404 = "http_404"
CATEGORY_HTTP_429 = "http_429"
CATEGORY_HTTP_4XX = "http_4xx"
CATEGORY_HTTP_5XX = "http_5xx"
CATEGORY_PLAYWRIGHT_TIMEOUT = "playwright_timeout"
CATEGORY_ROBOTS = "robots"
CATEGORY_NON_HTML = "non_html"
CATEGORY_CIRCUIT_OPEN = "circuit_open"
CATEGORY_STOPPED = "stopped"
CATEGORY_UNKNOWN = "unknown"

ERROR_CATEGORIES = (
    CATEGORY_DNS,
    CATEGORY_CONNECTION,
    CATEGORY_TIMEOUT,
    CATEGORY_TLS,
    CATEGORY_HTTP_401,
    CATEGORY_HTTP_403,
    CATEGORY_HTTP_404,
    CATEGORY_HTTP_429,
    CATEGORY_HTTP_4XX,
    CATEGORY_HTTP_5XX,
    CATEGORY_PLAYWRIGHT_TIMEOUT,
    CATEGORY_ROBOTS,
    CATEGORY_NON_HTML,
    CATEGORY_CIRCUIT_OPEN,
    CATEGORY_STOPPED,
    CATEGORY_UNKNOWN,
)

ERROR_LABELS = {
    CATEGORY_DNS: "DNS resolution failed",
    CATEGORY_CONNECTION: "Connection failed",
    CATEGORY_TIMEOUT: "Request timed out",
    CATEGORY_TLS: "TLS/SSL handshake failed",
    CATEGORY_HTTP_401: "HTTP 401 Unauthorized",
    CATEGORY_HTTP_403: "HTTP 403 Forbidden",
    CATEGORY_HTTP_404: "HTTP 404 Not Found",
    CATEGORY_HTTP_429: "HTTP 429 Rate Limited",
    CATEGORY_HTTP_4XX: "HTTP 4xx client error",
    CATEGORY_HTTP_5XX: "HTTP 5xx server error",
    CATEGORY_PLAYWRIGHT_TIMEOUT: "Browser render timed out",
    CATEGORY_ROBOTS: "Disallowed by robots.txt",
    CATEGORY_NON_HTML: "Non-HTML content",
    CATEGORY_CIRCUIT_OPEN: "Domain circuit breaker open",
    CATEGORY_STOPPED: "Stopped by user",
    CATEGORY_UNKNOWN: "Unexpected error",
}


def error_label(category: str) -> str:
    """Human-readable label for a DLQ/error category."""
    return ERROR_LABELS.get(category, (category or "unknown").replace("_", " ").capitalize())


# Categories worth another attempt.  Auth/robots/non-HTML failures are final:
# retrying them only wastes bandwidth and hammers the target server.
RETRYABLE_CATEGORIES = {
    CATEGORY_DNS,
    CATEGORY_CONNECTION,
    CATEGORY_TIMEOUT,
    CATEGORY_TLS,
    CATEGORY_HTTP_429,
    CATEGORY_HTTP_5XX,
    CATEGORY_PLAYWRIGHT_TIMEOUT,
    CATEGORY_CIRCUIT_OPEN,
    CATEGORY_UNKNOWN,
}

_DNS_SIGNS = (
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "getaddrinfo failed",
    "no address associated with hostname",
    "name resolution",
)
_TLS_SIGNS = (
    "ssl",
    "certificate verify failed",
    "certificateerror",
    "tls handshake",
)


def classify_error(exc: BaseException | None, status_code: int | None = None) -> str:
    """Map a fetch/extraction exception to a stable, user-facing category."""
    name = type(exc).__name__.lower() if exc is not None else ""
    module = type(exc).__module__.lower() if exc is not None else ""
    message = str(exc or "").lower()

    explicit = getattr(exc, "error_type", None)
    if explicit:
        return str(explicit)

    if "robotsdisallowed" in name:
        return CATEGORY_ROBOTS
    if "nonhtmlcontent" in name:
        return CATEGORY_NON_HTML
    if "playwright" in module or "playwright" in name or "playwright" in message:
        if "timeout" in name or "timeout" in message or "timed out" in message:
            return CATEGORY_PLAYWRIGHT_TIMEOUT

    if isinstance(exc, socket.gaierror) or any(sign in message for sign in _DNS_SIGNS):
        return CATEGORY_DNS
    if any(sign in message for sign in _TLS_SIGNS) or "sslerror" in name:
        return CATEGORY_TLS

    if status_code is None:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code > 0:
        if status_code in (401, 407):
            return CATEGORY_HTTP_401
        if status_code == 403:
            return CATEGORY_HTTP_403
        if status_code in (404, 410):
            return CATEGORY_HTTP_404
        if status_code == 429:
            return CATEGORY_HTTP_429
        if 500 <= status_code <= 599:
            return CATEGORY_HTTP_5XX
        if 400 <= status_code <= 499:
            return CATEGORY_HTTP_4XX

    if "timeout" in name or "timed out" in message or "timeout" in message:
        return CATEGORY_TIMEOUT
    if "connection" in name or "connection" in message:
        return CATEGORY_CONNECTION
    return CATEGORY_UNKNOWN


@dataclass
class RetryPolicy:
    """Exponential backoff with optional jitter and ``Retry-After`` support."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 60.0
    jitter: float = 0.2
    retryable: set[str] = field(default_factory=lambda: set(RETRYABLE_CATEGORIES))

    def should_retry(self, category: str, attempts: int) -> bool:
        """Return True when another attempt is allowed.

        ``attempts`` is the number of attempts already made (including the
        failure that triggered this decision).
        """
        return category in self.retryable and attempts < max(1, self.max_attempts)

    def next_delay(self, attempts: int, retry_after: float | None = None) -> float:
        """Seconds to wait before the next attempt."""
        exponent = max(0, attempts - 1)
        delay = min(self.max_delay, self.base_delay * (2 ** exponent))
        if retry_after is not None and retry_after > 0:
            delay = max(delay, min(self.max_delay, float(retry_after)))
        if self.jitter > 0:
            delay += random.uniform(0, self.jitter * max(delay, self.base_delay))
        return round(max(0.0, min(self.max_delay, delay)), 3)


@dataclass
class _DomainState:
    failures: int = 0
    opened_at: float = 0.0
    half_open: bool = False
    total_failures: int = 0
    total_successes: int = 0


class DomainCircuitBreaker:
    """In-memory per-domain circuit breaker.

    After ``failure_threshold`` consecutive failures a domain is opened for
    ``cooldown`` seconds.  Once the cooldown elapses a single half-open probe is
    allowed; a success closes the circuit, another failure re-opens it.
    """

    def __init__(self, failure_threshold: int = 5, cooldown: float = 30.0) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown = max(0.0, float(cooldown))
        self._domains: dict[str, _DomainState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def domain_for(url: str) -> str:
        return (urlparse(url).netloc or "").lower()

    def allow(self, domain: str) -> bool:
        now = time.monotonic()
        with self._lock:
            state = self._domains.get(domain)
            if state is None or state.opened_at == 0.0:
                return True
            if now - state.opened_at >= self.cooldown:
                state.half_open = True
                return True
            return False

    def record_success(self, domain: str) -> None:
        with self._lock:
            state = self._domains.setdefault(domain, _DomainState())
            state.failures = 0
            state.opened_at = 0.0
            state.half_open = False
            state.total_successes += 1

    def record_failure(self, domain: str) -> None:
        with self._lock:
            state = self._domains.setdefault(domain, _DomainState())
            state.failures += 1
            state.total_failures += 1
            if state.half_open or state.failures >= self.failure_threshold:
                state.opened_at = time.monotonic()
                state.half_open = False

    def retry_after(self, domain: str) -> float:
        """Seconds until a half-open probe is allowed."""
        with self._lock:
            state = self._domains.get(domain)
            if state is None or state.opened_at == 0.0:
                return 0.0
            remaining = self.cooldown - (time.monotonic() - state.opened_at)
            return max(0.0, remaining)

    def state(self, domain: str) -> str:
        with self._lock:
            state = self._domains.get(domain)
            if state is None or state.opened_at == 0.0:
                return "closed"
            if time.monotonic() - state.opened_at >= self.cooldown:
                return "half_open"
            return "open"

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            result: dict[str, dict[str, Any]] = {}
            for domain, state in self._domains.items():
                if state.opened_at == 0.0:
                    status = "closed"
                    remaining = 0.0
                elif now - state.opened_at >= self.cooldown:
                    status = "half_open"
                    remaining = 0.0
                else:
                    status = "open"
                    remaining = round(self.cooldown - (now - state.opened_at), 2)
                result[domain] = {
                    "state": status,
                    "consecutive_failures": state.failures,
                    "total_failures": state.total_failures,
                    "total_successes": state.total_successes,
                    "retry_after": remaining,
                }
            return result


class AdaptiveRateLimiter:
    """Per-domain adaptive delay that backs off on throttling or errors.

    The crawler starts at the user's configured delay.  Every throttled request
    doubles the domain delay (up to ``max_delay``); successful requests slowly
    relax it back toward the configured base delay.
    """

    def __init__(self, base_delay: float, max_delay: float = 30.0) -> None:
        self.base_delay = max(0.0, float(base_delay))
        self.max_delay = max(self.base_delay, float(max_delay))
        self._delays: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._lock = threading.RLock()

    def delay_for(self, domain: str) -> float:
        with self._lock:
            return self._delays.get(domain, self.base_delay)

    def schedule(self, domain: str) -> float:
        """Reserve a request slot and return the number of seconds to wait."""
        with self._lock:
            delay = self._delays.get(domain, self.base_delay)
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            target = max(now, last + delay)
            self._last_request[domain] = target
            return max(0.0, target - now)

    def record_success(self, domain: str) -> None:
        with self._lock:
            current = self._delays.get(domain, self.base_delay)
            if current <= self.base_delay:
                self._delays[domain] = self.base_delay
            else:
                self._delays[domain] = max(self.base_delay, current * 0.75)

    def record_throttle(self, domain: str, retry_after: float | None = None) -> float:
        with self._lock:
            current = self._delays.get(domain, self.base_delay)
            backed_off = max(self.base_delay, current * 2.0)
            if retry_after and retry_after > 0:
                backed_off = max(backed_off, float(retry_after))
            self._delays[domain] = min(self.max_delay, backed_off)
            return self._delays[domain]

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {domain: round(value, 3) for domain, value in self._delays.items()}
