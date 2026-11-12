"""Configuration constants for the website scraper."""

from __future__ import annotations

import os
from pathlib import Path

REQUEST_TIMEOUT = 10
RENDER_TIMEOUT_MS = 15_000
REQUEST_DELAY_SECONDS = 0.2
RETRY_DELAY_SECONDS = 2.0
MAX_DEPTH = 5
DEFAULT_MAX_PAGES = 100
USER_AGENT = "LocalWebsiteContentScraper/1.0 (+https://example.com/scraper-info)"
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
SKIPPED_EXTENSIONS = {
    ".7z", ".avi", ".css", ".csv", ".doc", ".docx", ".gif", ".gz",
    ".ico", ".jpeg", ".jpg", ".js", ".json", ".m4a", ".mp3", ".mp4",
    ".pdf", ".png", ".ppt", ".pptx", ".rar", ".svg", ".tar", ".tgz",
    ".txt", ".wav", ".webm", ".webp", ".xls", ".xlsx", ".xml", ".zip",
}

# --- Phase 6: scale, resilience & queuing ---------------------------------

# Everything is stored locally in SQLite; no Redis, cloud service, or API key
# is required. Override the location with WEBSITE_SCRAPER_STATE_DIR.
STATE_DIR_ENV = "WEBSITE_SCRAPER_STATE_DIR"
DEFAULT_STATE_DIR = Path(os.environ.get(STATE_DIR_ENV, Path.home() / ".website_scraper"))
STATE_DB_FILENAME = "state.db"

DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 30.0
DEFAULT_CIRCUIT_THRESHOLD = 5
DEFAULT_CIRCUIT_COOLDOWN = 60.0

# Errors that are worth another attempt (transient network/server pressure).
RETRYABLE_ERRORS = {
    "dns",
    "connection",
    "timeout",
    "http_429",
    "http_5xx",
    "circuit_open",
    "playwright_timeout",
}


def default_state_dir() -> Path:
    """Return the local directory used for crawl checkpoints and delta caches."""
    return Path(os.environ.get(STATE_DIR_ENV, DEFAULT_STATE_DIR)).expanduser()


def default_state_db() -> Path:
    """Return the default SQLite checkpoint database path."""
    return default_state_dir() / STATE_DB_FILENAME
