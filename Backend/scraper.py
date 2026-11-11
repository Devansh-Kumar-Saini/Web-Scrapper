"""Single-URL scrape service shared by the REST API and Python callers."""

from __future__ import annotations

import logging
from typing import Any

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
    schema: dict[str, Any] | str | None = None,
    respect_robots: bool = True,
    chunk_size: int = 0,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    extract_media: bool = False,
    download_media: bool = False,
    media_types: set[str] | list[str] | None = None,
    output_dir: str | None = None,
    impersonate: str | bool | None = None,
    proxy: str | None = None,
    delay: float = 0.0,
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
    fetcher = fetcher or Fetcher(
        logger=logger,
        respect_robots=respect_robots,
        delay=delay,
        impersonate=impersonate,
        proxy=proxy,
    )
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
            schema=schema,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            extract_media=extract_media,
            media_types=media_types,
        )
        if download_media and output_dir and document.media:
            try:
                from .media import MediaItem, download_media_file
            except ImportError:
                from media import MediaItem, download_media_file
            from pathlib import Path
            out_p = Path(output_dir)
            for m_dict in document.media:
                m_item = MediaItem(
                    page_url=m_dict.get("page_url", final_url),
                    media_type=m_dict.get("media_type", "image"),
                    media_url=m_dict.get("media_url", ""),
                    filename=m_dict.get("filename", ""),
                    extension=m_dict.get("extension", ""),
                    alt=m_dict.get("alt", ""),
                )
                if download_media_file(m_item, out_p, session=fetcher.session):
                    m_dict["downloaded_path"] = m_item.downloaded_path
                    m_dict["download_status"] = m_item.download_status
                    m_dict["size_bytes"] = m_item.size_bytes
        document.status_code = result.status_code
        return document
    finally:
        if owns_renderer and renderer is not None:
            renderer.close()
        if owns_fetcher:
            fetcher.close()
