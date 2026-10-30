"""Configuration constants for the website scraper."""

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
