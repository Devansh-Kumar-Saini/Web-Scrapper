"""Sitemap discovery, fetching, and parsing for rapid crawler seed population."""

from __future__ import annotations

import gzip
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


def parse_sitemap_entries(content: str | bytes) -> tuple[list[dict[str, str]], list[str]]:
    """Parse a sitemap and keep each page's ``lastmod`` timestamp.

    Returns ``(entries, sub_sitemap_urls)`` where each entry is
    ``{"url": ..., "lastmod": ...}``.  ``lastmod`` may be an empty string.
    """
    if isinstance(content, str):
        content_bytes = content.encode("utf-8", errors="replace")
    else:
        content_bytes = content

    entries: list[dict[str, str]] = []
    sub_sitemaps: list[str] = []
    seen: set[str] = set()

    def _local(tag: str) -> str:
        return tag.split("}")[-1].lower() if "}" in tag else tag.lower()

    try:
        root = ET.fromstring(content_bytes)
        root_tag = _local(root.tag)
        for elem in root:
            if _local(elem.tag) == "sitemap":
                for child in elem:
                    if _local(child.tag) == "loc" and child.text:
                        loc = child.text.strip()
                        if loc.startswith(("http://", "https://")):
                            sub_sitemaps.append(loc)
                continue
            if _local(elem.tag) != "url":
                continue
            loc = ""
            lastmod = ""
            for child in elem:
                child_tag = _local(child.tag)
                if child_tag == "loc" and child.text:
                    loc = child.text.strip()
                elif child_tag == "lastmod" and child.text:
                    lastmod = child.text.strip()
            if loc.startswith(("http://", "https://")) and loc not in seen:
                seen.add(loc)
                entries.append({"url": loc, "lastmod": lastmod})
        if root_tag == "sitemapindex":
            for entry in entries:
                sub_sitemaps.append(entry["url"])
            entries = []
    except Exception as exc:
        logger.debug("XML parse failed, attempting regex entry extraction: %s", exc)
        raw_text = content_bytes.decode("utf-8", errors="replace")
        is_index = "sitemapindex" in raw_text.lower()
        for match in re.finditer(
            r"<url>(.*?)</url>", raw_text, re.IGNORECASE | re.DOTALL
        ):
            block = match.group(1)
            loc_match = re.search(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", block, re.IGNORECASE)
            lastmod_match = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block, re.IGNORECASE)
            if loc_match:
                loc = loc_match.group(1)
                if loc not in seen:
                    seen.add(loc)
                    entries.append({
                        "url": loc,
                        "lastmod": lastmod_match.group(1) if lastmod_match else "",
                    })
        if is_index:
            locs = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", raw_text, re.IGNORECASE)
            sub_sitemaps.extend(locs)
            entries = []

    return entries, list(dict.fromkeys(sub_sitemaps))


def parse_sitemap_xml(content: str | bytes) -> tuple[list[str], list[str]]:
    """Parse XML sitemap content and return (page_urls, sub_sitemap_urls).

    Supports standard sitemaps (<urlset>) and sitemap indexes (<sitemapindex>).
    Gracefully falls back to regex matching if XML parsing encounters syntax errors.
    """
    page_urls: list[str] = []
    sub_sitemaps: list[str] = []

    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content

    try:
        root = ET.fromstring(content_bytes)
        local_tag = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()

        for elem in root:
            elem_local = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()

            if elem_local == "url":
                for child in elem:
                    child_local = child.tag.split("}")[-1].lower() if "}" in child.tag else child.tag.lower()
                    if child_local == "loc" and child.text:
                        loc = child.text.strip()
                        if loc.startswith(("http://", "https://")):
                            page_urls.append(loc)
            elif elem_local == "sitemap":
                for child in elem:
                    child_local = child.tag.split("}")[-1].lower() if "}" in child.tag else child.tag.lower()
                    if child_local == "loc" and child.text:
                        loc = child.text.strip()
                        if loc.startswith(("http://", "https://")):
                            sub_sitemaps.append(loc)
            elif elem_local == "loc" and elem.text:
                loc = elem.text.strip()
                if loc.startswith(("http://", "https://")):
                    if local_tag == "sitemapindex":
                        sub_sitemaps.append(loc)
                    else:
                        page_urls.append(loc)
    except Exception as exc:
        logger.debug("XML parse failed, attempting regex extraction: %s", exc)
        raw_text = content_bytes.decode("utf-8", errors="replace")
        locs = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", raw_text, re.IGNORECASE)
        is_index = "sitemapindex" in raw_text.lower()
        if is_index:
            sub_sitemaps.extend(locs)
        else:
            page_urls.extend(locs)

    return list(dict.fromkeys(page_urls)), list(dict.fromkeys(sub_sitemaps))


def discover_sitemap_urls(
    seed_url: str,
    session: Any = None,
    robots_content: str | None = None,
    timeout: int = 5,
) -> list[str]:
    """Discover possible sitemap URLs from robots.txt and common locations."""
    parsed = urlparse(seed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    found: list[str] = []

    # 1. Check robots.txt for Sitemap directives
    if robots_content:
        for line in robots_content.splitlines():
            line_str = line.strip()
            if line_str.lower().startswith("sitemap:"):
                _, _, sitemap_path = line_str.partition(":")
                candidate = sitemap_path.strip()
                if candidate.startswith(("http://", "https://")):
                    found.append(candidate)
                elif candidate:
                    found.append(urljoin(origin, candidate))

    # 2. Check common default sitemap locations if none found yet
    candidates = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap/sitemap.xml",
    ]

    sess = session or requests.Session()
    for candidate in candidates:
        if candidate in found:
            continue
        try:
            resp = sess.head(candidate, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                found.append(candidate)
                break
        except Exception:
            continue

    if not found:
        # Fall back to default sitemap.xml even if HEAD was inconclusive
        found.append(f"{origin}/sitemap.xml")

    return list(dict.fromkeys(found))


def fetch_sitemap_urls(
    sitemap_url: str,
    session: Any = None,
    max_urls: int = 1000,
    max_depth: int = 3,
    timeout: int = 10,
) -> list[str]:
    """Fetch and parse a sitemap URL recursively up to max_depth."""
    sess = session or requests.Session()
    visited_sitemaps: set[str] = set()
    sitemap_queue: list[tuple[str, int]] = [(sitemap_url, 0)]
    all_pages: list[str] = []

    while sitemap_queue and len(all_pages) < max_urls:
        current_url, depth = sitemap_queue.pop(0)
        if current_url in visited_sitemaps or depth > max_depth:
            continue
        visited_sitemaps.add(current_url)

        try:
            resp = sess.get(current_url, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                continue

            content = resp.content
            if current_url.endswith(".gz") or content[:2] == b"\x1f\x8b":
                try:
                    content = gzip.decompress(content)
                except Exception:
                    pass

            pages, sub_sitemaps = parse_sitemap_xml(content)

            for p in pages:
                if p not in all_pages:
                    all_pages.append(p)
                    if len(all_pages) >= max_urls:
                        break

            if depth < max_depth and len(all_pages) < max_urls:
                for sub in sub_sitemaps:
                    if sub not in visited_sitemaps:
                        sitemap_queue.append((sub, depth + 1))
        except Exception as exc:
            logger.warning("Failed to fetch or parse sitemap %s: %s", current_url, exc)
            continue

    return all_pages[:max_urls]


def fetch_sitemap_entries(
    sitemap_url: str,
    session: Any = None,
    max_urls: int = 1000,
    max_depth: int = 3,
    timeout: int = 10,
) -> list[dict[str, str]]:
    """Fetch sitemaps recursively and return page URLs with ``lastmod`` values."""
    sess = session or requests.Session()
    visited_sitemaps: set[str] = set()
    sitemap_queue: list[tuple[str, int]] = [(sitemap_url, 0)]
    all_entries: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    while sitemap_queue and len(all_entries) < max_urls:
        current_url, depth = sitemap_queue.pop(0)
        if current_url in visited_sitemaps or depth > max_depth:
            continue
        visited_sitemaps.add(current_url)

        try:
            resp = sess.get(current_url, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                continue

            content = resp.content
            if current_url.endswith(".gz") or content[:2] == b"\x1f\x8b":
                try:
                    content = gzip.decompress(content)
                except Exception:
                    pass

            entries, sub_sitemaps = parse_sitemap_entries(content)
            for entry in entries:
                url = entry.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_entries.append(entry)
                if len(all_entries) >= max_urls:
                    break

            if depth < max_depth and len(all_entries) < max_urls:
                for sub in sub_sitemaps:
                    if sub not in visited_sitemaps:
                        sitemap_queue.append((sub, depth + 1))
        except Exception as exc:
            logger.warning("Failed to fetch or parse sitemap %s: %s", current_url, exc)
            continue

    return all_entries[:max_urls]
