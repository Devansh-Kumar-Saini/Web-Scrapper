"""Backend package for the website content scraper."""

from .config import DEFAULT_MAX_PAGES, MAX_DEPTH
from .crawler import Crawler, Page, normalize_url
from .extractor import PageContent, chunk_text, extract_content, extract_structured, validate_selectors
from .fetcher import Fetcher, FetchError, NonHtmlContent, RobotsDisallowed
from .filters import URLFilter
from .renderer import PlaywrightRenderer
from .scraper import scrape_url
from .writer import OUTPUT_FORMATS, OutputWriter

__all__ = [
    "Crawler",
    "Page",
    "PageContent",
    "normalize_url",
    "chunk_text",
    "extract_content",
    "extract_structured",
    "validate_selectors",
    "scrape_url",
    "Fetcher",
    "FetchError",
    "NonHtmlContent",
    "RobotsDisallowed",
    "URLFilter",
    "PlaywrightRenderer",
    "OutputWriter",
    "OUTPUT_FORMATS",
    "DEFAULT_MAX_PAGES",
    "MAX_DEPTH",
]
