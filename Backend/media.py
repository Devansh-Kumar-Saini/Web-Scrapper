"""Media extraction, categorization, manifest generation, and asset downloading."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urldefrag, urljoin, urlparse

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# Extension mappings
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".tiff", ".tif", ".avif", ".apng",
}
PDF_EXTENSIONS = {
    ".pdf",
}
DOC_EXTENSIONS = {
    ".doc", ".docx", ".odt", ".rtf", ".pages", ".dot", ".dotx",
}
PPT_EXTENSIONS = {
    ".ppt", ".pptx", ".odp", ".key", ".pps", ".ppsx",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".webm", ".ogg", ".ogv", ".mov", ".avi", ".wmv", ".mkv", ".m4v", ".flv", ".3gp",
}

MEDIA_CATEGORIES = ("image", "pdf", "doc", "ppt", "video")

CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "image": IMAGE_EXTENSIONS,
    "pdf": PDF_EXTENSIONS,
    "doc": DOC_EXTENSIONS,
    "ppt": PPT_EXTENSIONS,
    "video": VIDEO_EXTENSIONS,
}

ALL_MEDIA_EXTENSIONS: dict[str, str] = {}
for _cat, _exts in CATEGORY_EXTENSIONS.items():
    for _ext in _exts:
        ALL_MEDIA_EXTENSIONS[_ext] = _cat

_TYPE_ALIASES = {
    "images": "image",
    "image": "image",
    "img": "image",
    "pdfs": "pdf",
    "pdf": "pdf",
    "docs": "doc",
    "doc": "doc",
    "documents": "doc",
    "document": "doc",
    "ppts": "ppt",
    "ppt": "ppt",
    "presentations": "ppt",
    "presentation": "ppt",
    "videos": "video",
    "video": "video",
    "vid": "video",
}

_MANIFEST_CSV_FIELDS = (
    "page_url",
    "media_type",
    "media_url",
    "filename",
    "extension",
    "alt",
    "download_status",
    "downloaded_path",
    "size_bytes",
)


def normalize_media_type(name: str) -> str | None:
    """Normalize user input string to one of the canonical media categories."""
    clean = str(name).strip().lower()
    return _TYPE_ALIASES.get(clean)


def parse_media_types(raw: str | Iterable[str] | None) -> set[str]:
    """Parse a comma-separated string or iterable of media types into a set of canonical categories."""
    if raw is None:
        return set(MEDIA_CATEGORIES)
    if isinstance(raw, str):
        candidates = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        candidates = [str(part).strip() for part in raw if str(part).strip()]

    result: set[str] = set()
    for item in candidates:
        norm = normalize_media_type(item)
        if norm:
            result.add(norm)
    return result or set(MEDIA_CATEGORIES)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sanitize_filename(name: str, fallback: str = "asset") -> str:
    """Produce a safe filename for saving to disk, avoiding path traversal and illegal characters."""
    clean = re.sub(r'[\/\\:\*\?"<>\|\x00-\x1f]', "_", name).strip(". ")
    clean = re.sub(r"_+", "_", clean)
    if not clean:
        clean = fallback
    return clean[:120]


def extract_filename_and_ext(url: str, default_stem: str = "media", default_ext: str = "") -> tuple[str, str]:
    """Extract a sanitized filename and extension from a media URL."""
    parsed = urlparse(url)
    raw_path = unquote(parsed.path)
    pure = PurePosixPath(raw_path)
    stem = pure.stem.strip()
    ext = pure.suffix.lower().strip()

    if not ext and default_ext:
        ext = default_ext if default_ext.startswith(".") else f".{default_ext}"

    if not stem or stem == "/":
        # Synthesize stem from domain or query if available
        if parsed.query:
            query_slug = re.sub(r"[^a-zA-Z0-9]+", "_", parsed.query).strip("_")[:20]
            stem = f"{default_stem}_{query_slug}" if query_slug else default_stem
        else:
            stem = default_stem

    filename = f"{sanitize_filename(stem)}{ext}"
    return filename, ext


def classify_media_url(url: str, tag_hint: str | None = None) -> tuple[str | None, str]:
    """Determine media category and extension for a URL.

    Returns (category, extension) or (None, "") if not recognized.
    """
    clean_url, _ = urldefrag(url.strip())
    parsed = urlparse(clean_url)
    ext = PurePosixPath(parsed.path.lower()).suffix

    if ext in ALL_MEDIA_EXTENSIONS:
        return ALL_MEDIA_EXTENSIONS[ext], ext

    # Tag hints for URLs without clear extensions (e.g. dynamic CDN images or video endpoints)
    if tag_hint in {"img", "picture", "source_img", "image"}:
        return "image", ext or ".jpg"
    if tag_hint in {"video", "source_video"}:
        return "video", ext or ".mp4"

    return None, ext


@dataclass
class MediaItem:
    """Represents a single media asset found on a webpage."""

    page_url: str
    media_type: str  # 'image', 'pdf', 'doc', 'ppt', 'video'
    media_url: str
    filename: str = ""
    extension: str = ""
    alt: str = ""
    downloaded_path: str = ""
    download_status: str = "pending"  # 'pending', 'downloaded', 'failed', 'skipped'
    size_bytes: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        if not self.filename:
            self.filename, ext = extract_filename_and_ext(self.media_url, default_stem=f"{self.media_type}_asset")
            if not self.extension:
                self.extension = ext

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_url": self.page_url,
            "media_type": self.media_type,
            "media_url": self.media_url,
            "filename": self.filename,
            "extension": self.extension,
            "alt": self.alt,
            "downloaded_path": self.downloaded_path,
            "download_status": self.download_status,
            "size_bytes": self.size_bytes,
        }


def _parse_srcset(srcset: str) -> list[str]:
    """Extract individual candidate URLs from an HTML srcset attribute."""
    urls: list[str] = []
    for part in srcset.split(","):
        candidate = part.strip().split()[0] if part.strip() else ""
        if candidate:
            urls.append(candidate)
    return urls


def extract_media_from_html(
    html: str,
    page_url: str,
    allowed_types: set[str] | None = None,
) -> list[MediaItem]:
    """Extract all supported media items (images, pdfs, docs, ppts, videos) from an HTML document."""
    if not html or not html.strip():
        return []

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []

    types_filter = allowed_types if allowed_types is not None else set(MEDIA_CATEGORIES)
    items: list[MediaItem] = []
    seen_urls: set[str] = set()

    def add_candidate(raw_url: str, tag_hint: str | None = None, alt_text: str = "") -> None:
        candidate = (raw_url or "").strip()
        if not candidate or candidate.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return
        abs_url = urljoin(page_url, candidate)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            return
        if abs_url in seen_urls:
            return

        category, ext = classify_media_url(abs_url, tag_hint=tag_hint)
        if category and category in types_filter:
            seen_urls.add(abs_url)
            filename, _ = extract_filename_and_ext(abs_url, default_stem=f"{category}_file", default_ext=ext)
            items.append(
                MediaItem(
                    page_url=page_url,
                    media_type=category,
                    media_url=abs_url,
                    filename=filename,
                    extension=ext,
                    alt=_clean_text(alt_text),
                )
            )

    # 1. <img> tags
    for img in soup.find_all("img"):
        alt_text = img.get("alt") or img.get("title") or ""
        # Check src, data-src, data-lazy-src
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            val = img.get(attr)
            if val:
                add_candidate(str(val), tag_hint="img", alt_text=alt_text)
        # Check srcset
        srcset = img.get("srcset")
        if srcset:
            for src_cand in _parse_srcset(str(srcset)):
                add_candidate(src_cand, tag_hint="img", alt_text=alt_text)

    # 2. <picture><source srcset="..."> tags
    for picture in soup.find_all("picture"):
        for source in picture.find_all("source"):
            srcset = source.get("srcset")
            if srcset:
                for src_cand in _parse_srcset(str(srcset)):
                    add_candidate(src_cand, tag_hint="picture")

    # 3. <video> tags and <source>
    for video in soup.find_all("video"):
        alt_text = video.get("title") or video.get("aria-label") or ""
        src = video.get("src")
        if src:
            add_candidate(str(src), tag_hint="video", alt_text=alt_text)
        poster = video.get("poster")
        if poster:
            add_candidate(str(poster), tag_hint="img", alt_text=f"Video Poster: {alt_text}")
        for source in video.find_all("source"):
            s_src = source.get("src")
            if s_src:
                add_candidate(str(s_src), tag_hint="video", alt_text=alt_text)

    # 4. <embed> and <object> tags (e.g. PDFs or media players)
    for embed in soup.find_all("embed", src=True):
        add_candidate(str(embed["src"]), tag_hint=None)
    for obj in soup.find_all("object", data=True):
        add_candidate(str(obj["data"]), tag_hint=None)

    # 5. <a> anchor links pointing to media files (PDFs, Docs, PPTs, Images, Videos)
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        link_text = link.get_text(" ", strip=True) or link.get("title") or ""
        add_candidate(href, tag_hint=None, alt_text=link_text)

    return items


def download_media_file(
    item: MediaItem,
    output_dir: Path,
    session: Any = None,
    timeout: int = 20,
    max_bytes: int = 150 * 1024 * 1024,
) -> bool:
    """Download a single media asset to disk inside ``output_dir/media/<media_type>/``."""
    try:
        category_dir = output_dir / "media" / item.media_type
        category_dir.mkdir(parents=True, exist_ok=True)

        target_file = category_dir / item.filename
        counter = 2
        stem = Path(item.filename).stem
        ext = item.extension or Path(item.filename).suffix

        # Avoid overwriting distinct files with the same name
        while target_file.exists():
            target_file = category_dir / f"{stem}_{counter}{ext}"
            counter += 1

        client = session or (requests.Session() if requests else None)
        if client is None:
            item.download_status = "failed"
            item.error = "HTTP client not available"
            return False

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Referer": item.page_url,
        }

        with client.get(item.media_url, headers=headers, stream=True, timeout=timeout) as response:
            if response.status_code >= 400:
                item.download_status = "failed"
                item.error = f"HTTP {response.status_code}"
                return False

            total = 0
            with target_file.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        handle.close()
                        target_file.unlink(missing_ok=True)
                        item.download_status = "failed"
                        item.error = f"File exceeded maximum limit ({max_bytes} bytes)"
                        return False
                    handle.write(chunk)

            item.filename = target_file.name
            item.downloaded_path = f"media/{item.media_type}/{target_file.name}"
            item.download_status = "downloaded"
            item.size_bytes = total
            return True

    except Exception as exc:
        item.download_status = "failed"
        item.error = str(exc)
        return False


class MediaCollector:
    """Thread-safe collector for media assets discovered across crawled pages."""

    def __init__(
        self,
        allowed_types: set[str] | None = None,
        download: bool = False,
        session: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.allowed_types = allowed_types if allowed_types is not None else set(MEDIA_CATEGORIES)
        self.download = bool(download)
        self.session = session
        self.logger = logger or logging.getLogger(__name__)
        self.items: list[MediaItem] = []
        self._seen_media_urls: set[str] = set()
        self._lock = threading.Lock()
        self.downloaded_count = 0
        self.failed_downloads = 0

    def add_page_media(
        self,
        page_url: str,
        html: str,
        output_dir: Path | None = None,
    ) -> list[MediaItem]:
        """Extract media from page HTML and optionally download new items."""
        extracted = extract_media_from_html(html, page_url, allowed_types=self.allowed_types)
        new_items: list[MediaItem] = []

        with self._lock:
            for item in extracted:
                if item.media_url not in self._seen_media_urls:
                    self._seen_media_urls.add(item.media_url)
                    self.items.append(item)
                    new_items.append(item)

        if self.download and output_dir and new_items:
            for item in new_items:
                ok = download_media_file(item, output_dir, session=self.session)
                with self._lock:
                    if ok:
                        self.downloaded_count += 1
                    else:
                        self.failed_downloads += 1

        return new_items

    def write_manifests(self, output_dir: Path) -> tuple[Path, Path]:
        """Write media_manifest.json and media_manifest.csv into output_dir."""
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "media_manifest.json"
        csv_path = output_dir / "media_manifest.csv"

        with self._lock:
            records = [item.to_dict() for item in self.items]

        # 1. JSON manifest
        json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. CSV manifest
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_MANIFEST_CSV_FIELDS)
            writer.writeheader()
            for rec in records:
                # Keep fields aligned
                row = {k: rec.get(k, "") for k in _MANIFEST_CSV_FIELDS}
                writer.writerow(row)

        return json_path, csv_path

    def get_summary(self) -> dict[str, Any]:
        """Return counts by media category and download status."""
        with self._lock:
            by_category: dict[str, int] = {cat: 0 for cat in MEDIA_CATEGORIES}
            for item in self.items:
                by_category[item.media_type] = by_category.get(item.media_type, 0) + 1

            return {
                "total_media": len(self.items),
                "downloaded": self.downloaded_count,
                "failed": self.failed_downloads,
                "by_category": by_category,
            }
