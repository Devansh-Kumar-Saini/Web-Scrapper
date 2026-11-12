"""Polite breadth-first website crawling with optional durable checkpoints."""

from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

try:
    from .config import (
        DEFAULT_BACKOFF_BASE,
        DEFAULT_BACKOFF_MAX,
        DEFAULT_CIRCUIT_COOLDOWN,
        DEFAULT_CIRCUIT_THRESHOLD,
        DEFAULT_MAX_RETRIES,
        REQUEST_DELAY_SECONDS,
        SKIPPED_EXTENSIONS,
    )
    from .fetcher import Fetcher, FetchError, NonHtmlContent, RobotsDisallowed
    from .filters import URLFilter
    from .renderer import PlaywrightRenderer
    from .retry import CATEGORY_STOPPED, RetryPolicy, classify_error
    from .sitemap import discover_sitemap_urls, fetch_sitemap_entries, fetch_sitemap_urls
    from .state import CrawlStore, DeltaCache
except ImportError:  # pragma: no cover - direct script execution
    from config import (
        DEFAULT_BACKOFF_BASE,
        DEFAULT_BACKOFF_MAX,
        DEFAULT_CIRCUIT_COOLDOWN,
        DEFAULT_CIRCUIT_THRESHOLD,
        DEFAULT_MAX_RETRIES,
        REQUEST_DELAY_SECONDS,
        SKIPPED_EXTENSIONS,
    )
    from fetcher import Fetcher, FetchError, NonHtmlContent, RobotsDisallowed
    from filters import URLFilter
    from renderer import PlaywrightRenderer
    from retry import CATEGORY_STOPPED, RetryPolicy, classify_error
    from sitemap import discover_sitemap_urls, fetch_sitemap_entries, fetch_sitemap_urls
    from state import CrawlStore, DeltaCache


@dataclass
class Page:
    url: str
    depth: int
    title: str
    html: str
    extracted_document: Any = None
    status_code: int = 0
    content_hash: str = ""
    changed: bool = True
    unchanged: bool = False


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


_RE_HREF = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))',
    re.IGNORECASE,
)
_RE_TITLE = re.compile(r'<title\b[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)


def _extract_title_fast(html_content: str) -> str:
    m = _RE_TITLE.search(html_content)
    if m:
        cleaned = html_lib.unescape(m.group(1)).strip()
        if cleaned:
            # Clean up whitespace/newlines within title
            return " ".join(cleaned.split())
    return "Untitled page"


def _extract_hrefs_fast(html_content: str) -> list[str]:
    hrefs: list[str] = []
    for m in _RE_HREF.finditer(html_content):
        val = m.group(1) or m.group(2) or m.group(3)
        if val:
            cleaned = html_lib.unescape(val.strip().strip("'\"\\"))
            if (
                cleaned
                and not cleaned.startswith(("#", "javascript:", "mailto:", "tel:", "data:", "${"))
                and "${" not in cleaned
            ):
                hrefs.append(cleaned)
    return hrefs


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
        concurrency: int = 5,
        delay: float = REQUEST_DELAY_SECONDS,
        sitemap: bool = False,
        sitemap_url: str | None = None,
        impersonate: str | bool | None = None,
        proxy: str | None = None,
        render_js: bool = False,
        page_processor: Callable[[str, str, int], Any] | None = None,
        # --- Phase 6 ---
        store: CrawlStore | None = None,
        job_id: str | None = None,
        delta: DeltaCache | bool | None = None,
        resume: bool = False,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
        circuit_threshold: int = DEFAULT_CIRCUIT_THRESHOLD,
        circuit_cooldown: float = DEFAULT_CIRCUIT_COOLDOWN,
        adaptive_delay: bool = True,
        worker_id: str = "",
        on_failure: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.same_domain = same_domain
        self.logger = logger
        self.stop_event = stop_event
        self.on_page_crawled = on_page_crawled
        self.url_filter = URLFilter(include_patterns, exclude_patterns)
        self.concurrency = max(1, concurrency)
        self.delay = max(0.0, float(delay))
        self.sitemap = sitemap
        self.sitemap_url = sitemap_url
        self.render_js = bool(render_js)
        self.page_processor = page_processor
        self.store = store
        self.job_id = job_id
        if isinstance(delta, DeltaCache):
            self.delta_cache: DeltaCache | None = delta
        elif delta and store is not None:
            self.delta_cache = DeltaCache(store.db_path, logger=logger)
        else:
            self.delta_cache = None
        self.delta = self.delta_cache is not None
        self.resume = bool(resume)
        self.worker_id = worker_id or "local"
        self.on_failure = on_failure
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))
        self.backoff_max = max(0.1, float(backoff_max))
        self.circuit_threshold = max(1, int(circuit_threshold))
        self.circuit_cooldown = max(0.0, float(circuit_cooldown))
        self.adaptive_delay = bool(adaptive_delay)
        self.retry_policy = RetryPolicy(
            max_attempts=self.max_retries + 1,
            base_delay=self.backoff_base,
            max_delay=self.backoff_max,
        )
        self._sitemap_lastmods: dict[str, str] = {}
        self._stats_lock = threading.Lock()
        self.stats: dict[str, Any] = {
            "fetched": 0,
            "pages_changed": 0,
            "pages_unchanged": 0,
            "pages_skipped": 0,
            "pages_failed": 0,
            "pages_retried": 0,
            "links_discovered": 0,
            "job_id": job_id or "",
        }

        self._owns_fetcher = fetcher is None
        # With a durable queue, retries are scheduled across crawler iterations
        # (so they survive restarts); inline HTTP retries would double-count.
        inline_retries = 0 if (store is not None and job_id) else self.max_retries
        self.fetcher = fetcher or Fetcher(
            logger=logger,
            respect_robots=respect_robots,
            stop_event=stop_event,
            delay=self.delay,
            impersonate=impersonate,
            proxy=proxy,
            max_retries=inline_retries,
            backoff_base=self.backoff_base,
            backoff_max=self.backoff_max,
            circuit_threshold=self.circuit_threshold,
            circuit_cooldown=self.circuit_cooldown,
            cache=self.delta_cache,
            conditional=self.delta,
            adaptive_rate_limit=self.adaptive_delay,
        )
        self.session = self.fetcher.session
        self.renderer = renderer or PlaywrightRenderer(logger)
        self._render_lock = threading.Lock()
        self.skipped_reasons: list[str] = []

    # --- bookkeeping ---------------------------------------------------------

    def _stat(self, name: str, amount: int = 1) -> None:
        with self._stats_lock:
            self.stats[name] = int(self.stats.get(name, 0)) + amount

    def _render(self, url: str) -> str | None:
        """Render a JavaScript page locally when its HTTP body has no text."""
        return self.renderer.render(url)

    def _seed_domains(self, seeds: list[str]) -> set[str]:
        return {_root_domain(seed) for seed in seeds}

    def _candidate_links(self, html: str, final_url: str, depth: int, seed_domains: set[str]) -> list[str]:
        """Extract normalized, same-domain HTML links from a page."""
        if depth >= self.max_depth or not html:
            return []
        links: list[str] = []
        seen_local: set[str] = set()
        for raw_href in _extract_hrefs_fast(html):
            candidate = normalize_url(urljoin(final_url, raw_href))
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or not _is_html_candidate(candidate):
                continue
            if self.same_domain and _root_domain(candidate) not in seed_domains:
                continue
            if candidate in seen_local:
                continue
            seen_local.add(candidate)
            links.append(candidate)
        return links

    def _hash(self, html: str) -> str:
        return hashlib.sha256((html or "").encode("utf-8", errors="replace")).hexdigest()

    def _cached_links(self, cached: dict[str, Any] | None, seed_domains: set[str]) -> list[str]:
        if not cached:
            return []
        links: list[str] = []
        for raw in cached.get("links", []) or []:
            candidate = normalize_url(str(raw))
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or not _is_html_candidate(candidate):
                continue
            if self.same_domain and _root_domain(candidate) not in seed_domains:
                continue
            links.append(candidate)
        return list(dict.fromkeys(links))

    def _record_cache(
        self,
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
        content_hash: str = "",
        status_code: int = 0,
        links: list[str] | None = None,
        title: str = "",
    ) -> None:
        if self.delta_cache is None:
            return
        self.delta_cache.record(
            url,
            hash_value=content_hash,
            etag=etag,
            last_modified=last_modified,
            status_code=status_code,
            sitemap_lastmod=self._sitemap_lastmods.get(url, ""),
            title=title,
            links=links or [],
        )

    def _sitemap_unchanged(self, url: str, seed_domains: set[str], lastmod: str | None = None) -> Page | None:
        """Skip a URL entirely when sitemap ``lastmod`` and the cache agree."""
        if not self.delta or self.delta_cache is None:
            return None
        effective_lastmod = lastmod or self._sitemap_lastmods.get(url)
        if not effective_lastmod:
            return None
        if not self.delta_cache.should_skip_before_fetch(url, effective_lastmod):
            return None
        cached = self.delta_cache.get(url)
        if not cached:
            return None
        return Page(
            url=url,
            depth=0,
            title="Unchanged (sitemap lastmod)",
            html="",
            status_code=304,
            content_hash=str(cached.get("content_hash", "")),
            changed=False,
            unchanged=True,
        )

    # --- per-URL pipeline ----------------------------------------------------

    def _fetch_outcome(
        self,
        url: str,
        depth: int,
        seed_domains: set[str],
    ) -> dict[str, Any]:
        """Fetch, render, optionally delta-compare, and run the page processor."""
        try:
            result = self.fetcher.fetch(url)
        except RobotsDisallowed:
            with self._stats_lock:
                self.skipped_reasons.append(f"robots.txt: {url}")
            self.logger.info("Skipped disallowed by robots.txt: %s", url)
            self._stat("pages_skipped")
            return {"kind": "skip", "url": url, "reason": "robots.txt"}
        except NonHtmlContent:
            with self._stats_lock:
                self.skipped_reasons.append(f"non-HTML: {url}")
            self._stat("pages_skipped")
            return {"kind": "skip", "url": url, "reason": "non-HTML"}
        except FetchError as exc:
            if self.stop_event and self.stop_event.is_set():
                return {"kind": "stopped", "url": url}
            with self._stats_lock:
                self.skipped_reasons.append(f"request failure: {url}")
            self.logger.warning("Request failed for %s: %s", url, exc)
            return {
                "kind": "failed",
                "url": url,
                "depth": depth,
                "error_type": getattr(exc, "error_type", None) or classify_error(exc),
                "message": str(exc),
                "status_code": getattr(exc, "status_code", None),
                "retry_after": getattr(exc, "retry_after", None),
            }

        self._stat("fetched")
        final_url = normalize_url(result.final_url)
        status_code = int(getattr(result, "status_code", 0) or 0)
        cached = self.delta_cache.get(final_url) if self.delta and self.delta_cache else None

        if getattr(result, "not_modified", False):
            self._stat("pages_unchanged")
            links = self._cached_links(cached, seed_domains)
            self._record_cache(
                final_url,
                etag=getattr(result, "etag", ""),
                last_modified=getattr(result, "last_modified", ""),
                content_hash=getattr(result, "content_hash", "") or (cached or {}).get("content_hash", ""),
                status_code=304,
                links=links,
            )
            return {
                "kind": "unchanged",
                "url": final_url,
                "depth": depth,
                "status_code": 304,
                "content_hash": getattr(result, "content_hash", ""),
                "etag": getattr(result, "etag", ""),
                "last_modified": getattr(result, "last_modified", ""),
                "links": links,
                "page": Page(
                    url=final_url,
                    depth=depth,
                    title="Unchanged (HTTP 304)",
                    html="",
                    status_code=304,
                    content_hash=getattr(result, "content_hash", ""),
                    changed=False,
                    unchanged=True,
                ),
            }

        html = result.html
        if self.render_js:
            with self._render_lock:
                rendered_html = self._render(final_url)
            if rendered_html:
                html = rendered_html
        content_hash = getattr(result, "content_hash", "") or self._hash(html)

        if self.delta and cached and cached.get("content_hash") and cached["content_hash"] == content_hash:
            self._stat("pages_unchanged")
            links = self._candidate_links(html, final_url, depth, seed_domains)
            self._record_cache(
                final_url,
                etag=getattr(result, "etag", ""),
                last_modified=getattr(result, "last_modified", ""),
                content_hash=content_hash,
                status_code=status_code,
                links=links,
                title=_extract_title_fast(html),
            )
            self.logger.info("Unchanged content, skipping write: %s", final_url)
            return {
                "kind": "unchanged",
                "url": final_url,
                "depth": depth,
                "status_code": status_code,
                "content_hash": content_hash,
                "etag": getattr(result, "etag", ""),
                "last_modified": getattr(result, "last_modified", ""),
                "links": links,
                "page": Page(
                    url=final_url,
                    depth=depth,
                    title=_extract_title_fast(html),
                    html="",
                    status_code=status_code,
                    content_hash=content_hash,
                    changed=False,
                    unchanged=True,
                ),
            }

        title = _extract_title_fast(html)
        links = self._candidate_links(html, final_url, depth, seed_domains)
        self._stat("pages_changed")
        self._stat("links_discovered", len(links))

        extracted_doc = None
        if self.page_processor is not None:
            try:
                extracted_doc = self.page_processor(final_url, html, depth)
            except Exception as proc_exc:
                self.logger.warning("Extraction error for %s: %s", final_url, proc_exc)

        self._record_cache(
            final_url,
            etag=getattr(result, "etag", ""),
            last_modified=getattr(result, "last_modified", ""),
            content_hash=content_hash,
            status_code=status_code,
            links=links,
            title=title,
        )
        page = Page(
            final_url,
            depth,
            title,
            html,
            extracted_document=extracted_doc,
            status_code=status_code,
            content_hash=content_hash,
        )
        return {
            "kind": "page",
            "page": page,
            "url": final_url,
            "depth": depth,
            "status_code": status_code,
            "content_hash": content_hash,
            "etag": getattr(result, "etag", ""),
            "last_modified": getattr(result, "last_modified", ""),
            "links": links,
        }

    def _retry_delay(self, attempt: int, retry_after: float | None = None) -> float:
        return self.retry_policy.next_delay(attempt, retry_after)

    # --- public crawl --------------------------------------------------------

    def crawl(self, seeds: list[str]) -> Iterator[Page]:
        # Sitemap discovery and seed augmentation
        if self.sitemap or self.sitemap_url:
            sitemap_seeds: list[str] = []
            if self.sitemap_url:
                if self.delta:
                    entries = fetch_sitemap_entries(
                        self.sitemap_url, session=self.session, max_urls=self.max_pages
                    )
                else:
                    entries = [
                        {"url": u, "lastmod": ""}
                        for u in fetch_sitemap_urls(
                            self.sitemap_url, session=self.session, max_urls=self.max_pages
                        )
                    ]
                for entry in entries:
                    sitemap_seeds.append(entry["url"])
                    if entry.get("lastmod"):
                        self._sitemap_lastmods[normalize_url(entry["url"])] = entry["lastmod"]
            elif self.sitemap:
                for seed in seeds:
                    discovered = discover_sitemap_urls(seed, session=self.session)
                    for s_url in discovered:
                        if self.delta:
                            entries = fetch_sitemap_entries(
                                s_url,
                                session=self.session,
                                max_urls=self.max_pages - len(sitemap_seeds),
                            )
                        else:
                            entries = [
                                {"url": u, "lastmod": ""}
                                for u in fetch_sitemap_urls(
                                    s_url,
                                    session=self.session,
                                    max_urls=self.max_pages - len(sitemap_seeds),
                                )
                            ]
                        for entry in entries:
                            sitemap_seeds.append(entry["url"])
                            if entry.get("lastmod"):
                                self._sitemap_lastmods[normalize_url(entry["url"])] = entry["lastmod"]
                        if len(sitemap_seeds) >= self.max_pages:
                            break
                    if len(sitemap_seeds) >= self.max_pages:
                        break

            if sitemap_seeds:
                self.logger.info("Discovered %d URLs from sitemap(s)", len(sitemap_seeds))
                seeds = list(dict.fromkeys(seeds + sitemap_seeds))

        try:
            if self.store is not None and self.job_id:
                yield from self._crawl_persistent(seeds)
            elif self.concurrency > 1:
                yield from self._crawl_concurrent(seeds)
            else:
                yield from self._crawl_sequential(seeds)
        finally:
            self.renderer.close()
            if self._owns_fetcher:
                self.fetcher.close()

    # --- in-memory crawler (original behaviour) ------------------------------

    def _crawl_sequential(self, seeds: list[str]) -> Iterator[Page]:
        queue: deque[tuple[str, int, str]] = deque()
        seen: set[str] = set()
        seed_domains = self._seed_domains(seeds)
        for seed in seeds:
            normalized = normalize_url(seed)
            if normalized and normalized not in seen:
                queue.append((normalized, 0, _root_domain(normalized)))
                seen.add(normalized)
        queued_count = len(queue)

        while queue:
            if self.stop_event and self.stop_event.is_set():
                self.logger.info("Crawl stopped by request.")
                break

            url, depth, seed_domain = queue.popleft()
            outcome = self._fetch_outcome(url, depth, seed_domains)
            if outcome["kind"] == "stopped":
                break
            page = outcome.get("page")
            if page is not None:
                if self.on_page_crawled:
                    self.on_page_crawled(page)
                yield page
            if outcome["kind"] not in {"page", "unchanged"}:
                continue

            if depth >= self.max_depth:
                continue
            for candidate in outcome.get("links", []):
                if self.stop_event and self.stop_event.is_set():
                    break
                if candidate in seen:
                    continue
                seen.add(candidate)

                reason = self.url_filter.excluded_by(candidate)
                if reason:
                    with self._stats_lock:
                        self.skipped_reasons.append(f"{reason}: {candidate}")
                    self.logger.info("Skipped %s (%s)", candidate, reason)
                    continue
                if queued_count < self.max_pages:
                    queued_count += 1
                    queue.append((candidate, depth + 1, seed_domain))

    def _crawl_concurrent(self, seeds: list[str]) -> Iterator[Page]:
        import concurrent.futures

        frontier: deque[tuple[str, int, str]] = deque()
        seen: set[str] = set()
        seed_domains = self._seed_domains(seeds)
        for seed in seeds:
            normalized = normalize_url(seed)
            if normalized and normalized not in seen:
                frontier.append((normalized, 0, _root_domain(normalized)))
                seen.add(normalized)
        queued_count = len(frontier)

        state_lock = threading.Lock()
        active_futures: set[concurrent.futures.Future] = set()

        def worker_task(url: str, depth: int, seed_domain: str) -> dict[str, Any]:
            if self.stop_event and self.stop_event.is_set():
                return {"kind": "stopped", "url": url, "depth": depth}
            return self._fetch_outcome(url, depth, seed_domains)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency)
        try:
            nonlocal_queued = queued_count

            def schedule_workers() -> None:
                nonlocal nonlocal_queued
                while frontier and len(active_futures) < self.concurrency and not (
                    self.stop_event and self.stop_event.is_set()
                ):
                    u, d, s = frontier.popleft()
                    fut = executor.submit(worker_task, u, d, s)
                    active_futures.add(fut)

            with state_lock:
                schedule_workers()

            while True:
                if self.stop_event and self.stop_event.is_set():
                    self.logger.info("Crawl stopped by request.")
                    break

                with state_lock:
                    if not active_futures and not frontier:
                        break
                    current_active = list(active_futures)

                done, _ = concurrent.futures.wait(
                    current_active,
                    timeout=0.05,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                pages_to_yield: list[Page] = []
                with state_lock:
                    for fut in done:
                        active_futures.discard(fut)
                        try:
                            outcome = fut.result()
                        except Exception as exc:
                            self.logger.warning("Worker task error: %s", exc)
                            outcome = {"kind": "failed", "url": "", "error_type": "other", "message": str(exc)}

                        page = outcome.get("page")
                        if page is not None:
                            pages_to_yield.append(page)

                        if outcome["kind"] in {"page", "unchanged"} and not (
                            self.stop_event and self.stop_event.is_set()
                        ):
                            parent_depth = int(outcome.get("depth", 0))
                            for candidate in outcome.get("links", []):
                                if candidate in seen:
                                    continue
                                seen.add(candidate)
                                reason = self.url_filter.excluded_by(candidate)
                                if reason:
                                    with self._stats_lock:
                                        self.skipped_reasons.append(f"{reason}: {candidate}")
                                    self.logger.info("Skipped %s (%s)", candidate, reason)
                                    continue
                                if nonlocal_queued < self.max_pages:
                                    nonlocal_queued += 1
                                    frontier.append((candidate, parent_depth + 1, _root_domain(candidate)))

                    schedule_workers()

                for page in pages_to_yield:
                    if self.on_page_crawled:
                        self.on_page_crawled(page)
                    yield page
        finally:
            with state_lock:
                for fut in active_futures:
                    fut.cancel()
                active_futures.clear()
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

    # --- persistent queue crawler (Phase 6) ----------------------------------

    def _crawl_persistent(self, seeds: list[str]) -> Iterator[Page]:
        store = self.store
        job_id = self.job_id
        assert store is not None and job_id
        config = {
            "urls": seeds,
            "depth": self.max_depth,
            "max_pages": self.max_pages,
            "same_domain": self.same_domain,
        }
        if store.get_job(job_id) is None:
            store.create_job(job_id, config=config, status="running")
        store.update_job(job_id, status="running", stats=self.stats)
        if self.resume:
            requeued = store.reset_claimed(job_id)
            if requeued:
                self.logger.info("Resumed job %s (%d in-flight URL(s) requeued)", job_id, requeued)

        seed_domains = self._seed_domains(seeds)
        for seed in seeds:
            normalized = normalize_url(seed)
            if not normalized:
                continue
            store.enqueue(
                job_id,
                normalized,
                0,
                _root_domain(normalized),
                lastmod=self._sitemap_lastmods.get(normalized, ""),
                max_total=self.max_pages,
            )

        queue = store.queue_stats(job_id)
        self.logger.info(
            "Persistent queue active: job=%s, queue=%d, delta=%s",
            job_id,
            queue.get("total", 0),
            self.delta,
        )
        if self.concurrency > 1:
            yield from self._crawl_persistent_concurrent(seed_domains)
        else:
            yield from self._crawl_persistent_sequential(seed_domains)
        stopped = bool(self.stop_event and self.stop_event.is_set())
        store.update_job(job_id, status="stopped" if stopped else "completed", stats=self.stats)

    def _persistent_enqueue(self, outcome: dict[str, Any], seed_domains: set[str]) -> None:
        if self.store is None or not self.job_id:
            return
        if outcome["kind"] not in {"page", "unchanged"}:
            return
        parent_depth = int(outcome.get("depth", 0))
        for candidate in outcome.get("links", []):
            reason = self.url_filter.excluded_by(candidate)
            if reason:
                with self._stats_lock:
                    self.skipped_reasons.append(f"{reason}: {candidate}")
                self.logger.info("Skipped %s (%s)", candidate, reason)
                continue
            self.store.enqueue(
                self.job_id,
                candidate,
                parent_depth + 1,
                _root_domain(candidate),
                lastmod=self._sitemap_lastmods.get(candidate, ""),
                max_total=self.max_pages,
            )

    def _persistent_finish(self, outcome: dict[str, Any], claimed: dict[str, Any]) -> None:
        """Persist completion, retry, or DLQ state for one claimed URL."""
        assert self.store is not None and self.job_id
        kind = outcome.get("kind")
        url = outcome.get("url") or claimed["url"]
        depth = int(outcome.get("depth", claimed.get("depth", 0)))
        if kind in {"page", "unchanged"}:
            page = outcome.get("page")
            self.store.complete(
                self.job_id,
                url,
                depth=depth,
                status="done" if kind == "page" else "unchanged",
                status_code=int(outcome.get("status_code", 0) or 0),
                hash_value=str(outcome.get("content_hash", "") or ""),
                etag=str(outcome.get("etag", "") or ""),
                last_modified=str(outcome.get("last_modified", "") or ""),
                title=str(getattr(page, "title", "") or ""),
                attempts=int(claimed.get("attempts", 0) or 0) + 1,
            )
            return
        if kind == "skip":
            self.store.mark_skipped(
                self.job_id,
                url,
                str(outcome.get("reason", "skipped")),
                depth=depth,
                status_code=outcome.get("status_code"),
            )
            return
        if kind == "failed":
            attempts = int(claimed.get("attempts", 0) or 0) + 1
            error_type = str(outcome.get("error_type") or "unknown")
            retryable = self.retry_policy.should_retry(error_type, attempts)
            delay = self._retry_delay(attempts, outcome.get("retry_after")) if retryable else 0.0
            result = self.store.fail(
                self.job_id,
                url,
                depth=depth,
                category=error_type,
                message=str(outcome.get("message", "")),
                status_code=outcome.get("status_code"),
                retryable=retryable,
                delay_seconds=delay,
            )
            if result.get("retry"):
                self._stat("pages_retried")
                self.logger.info(
                    "Retry %d/%d scheduled for %s in %.1fs (%s)",
                    attempts,
                    self.max_retries,
                    url,
                    delay,
                    error_type,
                )
                return
            self._stat("pages_failed")
            self.logger.warning("Adding %s to the dead-letter queue (%s)", url, error_type)
            if self.on_failure is not None:
                page_entry = {
                    "url": url,
                    "depth": depth,
                    "error_category": error_type,
                    "status_code": outcome.get("status_code"),
                    "message": str(outcome.get("message", "")),
                    "attempts": attempts,
                }
                try:
                    self.on_failure(page_entry)
                except Exception as cb_exc:  # pragma: no cover - user callback
                    self.logger.debug("Failure callback raised: %s", cb_exc)

    def _persistent_precheck(self, claimed: dict[str, Any], seed_domains: set[str]) -> dict[str, Any] | None:
        """Skip an unchanged sitemap URL without making an HTTP request."""
        cached_page = self._sitemap_unchanged(
            claimed["url"],
            seed_domains,
            lastmod=str(claimed.get("sitemap_lastmod") or ""),
        )
        if cached_page is None:
            return None
        cached = self.delta_cache.get(claimed["url"]) if self.delta_cache else None
        links = self._cached_links(cached, seed_domains)
        self._stat("pages_unchanged")
        return {
            "kind": "unchanged",
            "url": claimed["url"],
            "depth": claimed["depth"],
            "status_code": 304,
            "content_hash": cached_page.content_hash,
            "links": links,
            "page": Page(
                url=claimed["url"],
                depth=claimed["depth"],
                title="Unchanged (sitemap lastmod)",
                html="",
                status_code=304,
                content_hash=cached_page.content_hash,
                changed=False,
                unchanged=True,
            ),
        }

    def _wait_for_retry(self, job_id: str) -> bool:
        """Wait for the next delayed retry. Return False when nothing is left."""
        if self.store is None:
            return False
        wait = self.store.next_available_in(job_id)
        if wait is None:
            return False
        seconds = min(max(wait, 0.01), 1.0)
        if self.stop_event:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)
        return True

    def _crawl_persistent_sequential(self, seed_domains: set[str]) -> Iterator[Page]:
        assert self.store is not None
        job_id = self.job_id or ""
        while True:
            if self.stop_event and self.stop_event.is_set():
                self.logger.info("Crawl stopped by request.")
                self.store.reset_claimed(job_id)
                break
            claimed = self.store.claim(job_id, worker_id=self.worker_id)
            if claimed is None:
                if not self._wait_for_retry(job_id):
                    break
                continue
            outcome = self._persistent_precheck(claimed, seed_domains)
            if outcome is None:
                outcome = self._fetch_outcome(claimed["url"], claimed["depth"], seed_domains)
            if outcome["kind"] == "stopped":
                self.store.reset_claimed(job_id)
                break
            self._persistent_enqueue(outcome, seed_domains)
            self._persistent_finish(outcome, claimed)
            self.store.update_job(job_id, stats=self.stats)
            page = outcome.get("page")
            if page is not None:
                if self.on_page_crawled:
                    self.on_page_crawled(page)
                yield page

    def _crawl_persistent_concurrent(self, seed_domains: set[str]) -> Iterator[Page]:
        import concurrent.futures

        assert self.store is not None
        store = self.store
        job_id = self.job_id or ""
        state_lock = threading.Lock()
        active: dict[concurrent.futures.Future, dict[str, Any]] = {}

        def worker_task(claimed: dict[str, Any]) -> dict[str, Any]:
            if self.stop_event and self.stop_event.is_set():
                return {"kind": "stopped", "url": claimed["url"], "depth": claimed["depth"]}
            prechecked = self._persistent_precheck(claimed, seed_domains)
            if prechecked is not None:
                return prechecked
            return self._fetch_outcome(claimed["url"], claimed["depth"], seed_domains)

        def schedule() -> int:
            scheduled = 0
            while len(active) < self.concurrency and not (self.stop_event and self.stop_event.is_set()):
                claimed = store.claim(job_id, worker_id=self.worker_id)
                if claimed is None:
                    break
                fut = executor.submit(worker_task, claimed)
                active[fut] = claimed
                scheduled += 1
            return scheduled

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency)
        try:
            schedule()
            while True:
                if self.stop_event and self.stop_event.is_set():
                    self.logger.info("Crawl stopped by request.")
                    break

                with state_lock:
                    if not active:
                        # No in-flight work: either delayed retries are waiting
                        # or the queue is exhausted.
                        if schedule() == 0:
                            if not self._wait_for_retry(job_id):
                                break
                        continue
                    current = list(active.keys())

                done, _ = concurrent.futures.wait(
                    current, timeout=0.05, return_when=concurrent.futures.FIRST_COMPLETED
                )
                pages_to_yield: list[Page] = []
                with state_lock:
                    for fut in done:
                        claimed = active.pop(fut)
                        try:
                            outcome = fut.result()
                        except Exception as exc:
                            self.logger.warning("Worker task error: %s", exc)
                            outcome = {
                                "kind": "failed",
                                "url": claimed["url"],
                                "depth": claimed["depth"],
                                "error_type": "unknown",
                                "message": str(exc),
                            }
                        if outcome["kind"] == "stopped":
                            continue
                        self._persistent_enqueue(outcome, seed_domains)
                        self._persistent_finish(outcome, claimed)
                        page = outcome.get("page")
                        if page is not None:
                            pages_to_yield.append(page)
                    store.update_job(job_id, stats=self.stats)
                    schedule()

                for page in pages_to_yield:
                    if self.on_page_crawled:
                        self.on_page_crawled(page)
                    yield page
        finally:
            with state_lock:
                for fut in active:
                    fut.cancel()
                active.clear()
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)
            if self.stop_event and self.stop_event.is_set():
                try:
                    store.reset_claimed(job_id)
                except Exception:
                    pass

    # --- checkpoint helpers --------------------------------------------------

    def record_page_saved(self, page: Page, filename: str) -> None:
        """Attach the saved filename to the durable checkpoint and delta cache."""
        url = getattr(page, "url", "")
        if not url or not filename:
            return
        if self.store is not None and self.job_id:
            try:
                self.store.set_file(self.job_id, url, filename)
            except Exception as exc:  # pragma: no cover - best effort
                self.logger.debug("Could not record saved file for %s: %s", url, exc)
        if self.delta_cache is not None:
            try:
                self.delta_cache.set_file(url, filename)
            except Exception as exc:  # pragma: no cover - best effort
                self.logger.debug("Could not record delta file for %s: %s", url, exc)

    def circuit_snapshot(self) -> dict[str, Any]:
        try:
            return dict(self.fetcher.circuit.snapshot())
        except Exception:
            return {}
