"""Single-URL scrape service shared by the REST API and Python callers."""

from __future__ import annotations

import logging

try:
    from .extractor import _DEFAULT_CHUNK_OVERLAP, PageContent, extract_structured, validate_selectors
    from .fetcher import Fetcher
    from .renderer import PlaywrightRenderer
except ImportError:  # pragma: no cover - direct script execution
    from extractor import _DEFAULT_CHUNK_OVERLAP, PageContent, extract_structured, validate_selectors
    from fetcher import Fetcher
    from renderer import PlaywrightRenderer


def scrape_url(
    url: str,
    *,
    render_js: bool = False,
    target_selector: str | None = None,
    exclude_selectors: list[str] | None = None,
    respect_robots: bool = True,
    chunk_size: int = 0,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    logger: logging.Logger | None = None,
    fetcher: Fetcher | None = None,
    renderer: PlaywrightRenderer | None = None,
) -> PageContent:
    """Fetch and extract a single URL immediately.

    Raises :class:`Backend.fetcher.FetchError` subclasses on network, robots,
    or content-type failures so callers can map them to HTTP status codes.
    """
    logger = logger or logging.getLogger(__name__)
    validate_selectors(target_selector, exclude_selectors)
    owns_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(logger=logger, respect_robots=respect_robots)
    owns_renderer = renderer is None and render_js
    renderer = renderer or (PlaywrightRenderer(logger) if render_js else None)

    try:
        result = fetcher.fetch(url)
        html = result.html
        final_url = result.final_url or url

        if render_js and renderer is not None:
            rendered_html = renderer.render(final_url)
            if rendered_html:
                html = rendered_html

        document = extract_structured(
            html,
            url=final_url,
            target_selector=target_selector,
            exclude_selectors=exclude_selectors,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        document.status_code = result.status_code
        return document
    finally:
        if owns_renderer and renderer is not None:
            renderer.close()
        if owns_fetcher:
            fetcher.close()
