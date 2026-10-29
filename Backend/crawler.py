"""Polite breadth-first website crawling."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

try:
    from .config import SKIPPED_EXTENSIONS
    from .fetcher import Fetcher, FetchError, NonHtmlContent, RobotsDisallowed
    from .filters import URLFilter
    from .renderer import PlaywrightRenderer
except ImportError:  # pragma: no cover - direct script execution
    from config import SKIPPED_EXTENSIONS
    from fetcher import Fetcher, FetchError, NonHtmlContent, RobotsDisallowed
    from filters import URLFilter
    from renderer import PlaywrightRenderer


@dataclass
class Page:
    url: str
    depth: int
    title: str
    html: str


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    path = parsed.path or "/"
    # Treat /about-us and /about-us/ as the same page so crawls do not duplicate content.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.params, parsed.query, ""))


def _root_domain(url: str) -> str:
    return urlparse(url).hostname or ""


def _is_html_candidate(url: str) -> bool:
    suffix = PurePosixPath(urlparse(url).path.lower()).suffix
    return suffix not in SKIPPED_EXTENSIONS


class Crawler:
    def __init__(
        self,
        max_depth: int,
        max_pages: int,
        same_domain: bool,
        logger: logging.Logger,
        stop_event: threading.Event | None = None,
        on_page_crawled: Callable[[Page], None] | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        respect_robots: bool = True,
        fetcher: Fetcher | None = None,
        renderer: PlaywrightRenderer | None = None,
    ) -> None:
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.same_domain = same_domain
        self.logger = logger
        self.stop_event = stop_event
        self.on_page_crawled = on_page_crawled
        self.url_filter = URLFilter(include_patterns, exclude_patterns)
        self._owns_fetcher = fetcher is None
        self.fetcher = fetcher or Fetcher(
            logger=logger,
            respect_robots=respect_robots,
            stop_event=stop_event,
        )
        self.session = self.fetcher.session
        self.renderer = renderer or PlaywrightRenderer(logger)
        self.skipped_reasons: list[str] = []

    def _render(self, url: str) -> str | None:
        """Render a JavaScript page locally when its HTTP body has no text."""
        return self.renderer.render(url)

    def crawl(self, seeds: list[str]) -> Iterator[Page]:
        queue: deque[tuple[str, int, str]] = deque()
        seen: set[str] = set()
        seed_domains = {_root_domain(seed) for seed in seeds}
        for seed in seeds:
            normalized = normalize_url(seed)
            if normalized and normalized not in seen:
                queue.append((normalized, 0, _root_domain(normalized)))
                seen.add(normalized)
        queued_count = len(queue)

        try:
            while queue:
                if self.stop_event and self.stop_event.is_set():
                    self.logger.info("Crawl stopped by request.")
                    break

                url, depth, seed_domain = queue.popleft()

                try:
                    result = self.fetcher.fetch(url)
                except RobotsDisallowed:
                    self.skipped_reasons.append(f"robots.txt: {url}")
                    self.logger.info("Skipped disallowed by robots.txt: %s", url)
                    continue
                except NonHtmlContent:
                    self.skipped_reasons.append(f"non-HTML: {url}")
                    continue
                except FetchError as exc:
                    if self.stop_event and self.stop_event.is_set():
                        break
                    self.skipped_reasons.append(f"request failure: {url}")
                    self.logger.warning("Request failed for %s: %s", url, exc)
                    continue

                final_url = normalize_url(result.final_url)
                html = result.html
                soup = BeautifulSoup(html, "lxml")
                if len(soup.get_text(" ", strip=True)) < 20:
                    rendered_html = self._render(final_url)
                    if rendered_html:
                        html = rendered_html
                        soup = BeautifulSoup(html, "lxml")
                title = soup.title
                page = Page(final_url, depth, title.get_text(" ", strip=True) if title else "Untitled page", html)
                if self.on_page_crawled:
                    self.on_page_crawled(page)
                yield page

                if depth >= self.max_depth:
                    continue
                for link in soup.find_all("a", href=True):
                    if self.stop_event and self.stop_event.is_set():
                        break
                    candidate = normalize_url(urljoin(final_url, link["href"]))
                    parsed = urlparse(candidate)
                    if parsed.scheme not in {"http", "https"} or not _is_html_candidate(candidate):
                        continue
                    if self.same_domain and _root_domain(candidate) not in seed_domains:
                        continue
                    if candidate in seen:
                        continue
                    seen.add(candidate)

                    reason = self.url_filter.excluded_by(candidate)
                    if reason:
                        self.skipped_reasons.append(f"{reason}: {candidate}")
                        self.logger.info("Skipped %s (%s)", candidate, reason)
                        continue
                    if queued_count < self.max_pages:
                        queued_count += 1
                        queue.append((candidate, depth + 1, seed_domain))
        finally:
            self.renderer.close()
            if self._owns_fetcher:
                self.fetcher.close()
