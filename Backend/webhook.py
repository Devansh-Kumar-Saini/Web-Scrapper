"""Webhook delivery for crawl lifecycle events.

A webhook lets developers push a crawl summary straight into their own
ingestion service (RAG pipeline, queue, database, etc.) without polling the
REST API. Delivery is best-effort: a failing receiver must never break a crawl.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

_USER_AGENT = "website-scraper/1.1 (+webhook)"


def validate_webhook_url(value: str | None) -> str:
    """Return a normalized webhook URL or raise ``ValueError`` when invalid."""
    url = (value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("webhook_url must be a valid HTTP/HTTPS URL.")
    return url


def build_payload(
    *,
    event: str,
    status: str,
    urls: list[str],
    stats: dict[str, Any],
    output_dir: str,
    started_at: str = "",
    finished_at: str = "",
    error: str | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the JSON body POSTed to a webhook receiver."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event": event,
        "status": status,
        "urls": list(urls),
        "output_dir": output_dir,
        "stats": dict(stats),
        "started_at": started_at or now,
        "finished_at": finished_at or now,
        "error": error,
        "pages": list(pages or []),
    }


def deliver_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 10.0,
    logger: logging.Logger | None = None,
) -> tuple[bool, str]:
    """POST ``payload`` to ``webhook_url``.

    Returns ``(ok, message)``. Network and HTTP failures are reported, never
    raised, so webhook problems cannot abort a crawl or download.
    """
    log = logger or logging.getLogger(__name__)
    if not webhook_url:
        return False, "No webhook configured."
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
                "X-Webhook-Event": str(payload.get("event", "")),
            },
        )
    except requests.RequestException as exc:
        message = f"Webhook delivery failed: {exc}"
        log.warning(message)
        return False, message

    if 200 <= response.status_code < 300:
        message = f"Webhook delivered ({response.status_code})."
        log.info(message)
        return True, message

    message = f"Webhook receiver responded with HTTP {response.status_code}."
    log.warning(message)
    return False, message


def notify(
    webhook_url: str,
    *,
    event: str,
    status: str,
    urls: list[str],
    stats: dict[str, Any],
    output_dir: str,
    started_at: str = "",
    finished_at: str = "",
    error: str | None = None,
    pages: list[dict[str, Any]] | None = None,
    logger: logging.Logger | None = None,
) -> tuple[bool, str]:
    """Convenience wrapper that builds and delivers a single event."""
    payload = build_payload(
        event=event,
        status=status,
        urls=urls,
        stats=stats,
        output_dir=output_dir,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        pages=pages,
    )
    return deliver_webhook(webhook_url, payload, logger=logger)
