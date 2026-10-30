"""ZIP export helpers with download-time format conversion.

Crawls are stored on disk in the format chosen before the job starts. This
module lets the Results screen download the same crawl as Markdown, plain
text, JSON, or JSONL without re-crawling: existing artifacts are parsed back
into :class:`PageContent` objects and re-serialized through ``OutputWriter``.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

try:  # package imports
    from .extractor import PageContent
    from .writer import OUTPUT_FORMATS, OutputWriter
except ImportError:  # pragma: no cover - direct script execution
    from extractor import PageContent
    from writer import OUTPUT_FORMATS, OutputWriter

_FORMAT_ALIASES = {"markdown": "md", "text": "txt", "md": "md", "txt": "txt", "json": "json", "jsonl": "jsonl"}
_SKIP_FILES = {"index.json", "scrape_log.txt"}
_FRONT_MATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)
_PAGE_FIELDS = {item.name for item in fields(PageContent)}
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]*\)")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")
_MD_RULE_RE = re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE)


def normalize_format(value: str | None) -> str | None:
    """Map user-facing format names to ``OUTPUT_FORMATS`` entries.

    Returns ``None`` for "keep the original files" (empty / original / zip).
    """
    if value is None:
        return None
    fmt = str(value).strip().lower()
    if not fmt or fmt in {"original", "keep", "zip"}:
        return None
    fmt = _FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f"format must be one of: {', '.join(OUTPUT_FORMATS)} (or original).")
    return fmt


def _markdown_to_text(markdown: str) -> str:
    """Best-effort Markdown -> plain text used when only Markdown is stored."""
    text = _MD_IMAGE_RE.sub("", markdown)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_RULE_RE.sub("", text)
    text = _MD_EMPHASIS_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        return {}, content
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        try:
            value: Any = json.loads(raw)
        except (ValueError, TypeError):
            value = raw.strip("\"'")
        meta[key.strip()] = value
    return meta, content[match.end():]


def _parse_text_file(content: str) -> tuple[dict[str, Any], str]:
    """Parse the header block written for ``.txt`` documents."""
    lines = content.splitlines()
    meta: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if set(line.strip()) <= {"-"} and len(line.strip()) >= 3:
            index += 1
            break
        if ":" not in line:
            break
        key, _, raw = line.partition(":")
        meta[key.strip().lower()] = raw.strip()
        index += 1
    return meta, "\n".join(lines[index:]).strip()


def _record_from_mapping(data: dict[str, Any], *, fallback_title: str = "") -> dict[str, Any]:
    record = {key: value for key, value in data.items() if key in _PAGE_FIELDS and value is not None}
    record.setdefault("title", fallback_title or "Untitled page")
    record.setdefault("url", "")
    return record


def _records_from_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    fallback_title = path.stem.replace("_", " ").title()

    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(data, dict):
            return [_record_from_mapping(data, fallback_title=fallback_title)]
        if isinstance(data, list):
            return [
                _record_from_mapping(item, fallback_title=fallback_title)
                for item in data
                if isinstance(item, dict)
            ]
        return []

    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(_record_from_mapping(item, fallback_title=fallback_title))
        return records

    if suffix == ".md":
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        meta, body = _parse_front_matter(content)
        record = _record_from_mapping(meta, fallback_title=fallback_title)
        record["markdown"] = body.strip()
        record.setdefault("text", _markdown_to_text(body))
        return [record]

    if suffix == ".txt":
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        meta, body = _parse_text_file(content)
        record = _record_from_mapping(meta, fallback_title=fallback_title)
        record["text"] = body
        record.setdefault("markdown", body)
        return [record]

    return []


def parse_saved_pages(output_dir: Path) -> list[dict[str, Any]]:
    """Read every saved page in ``output_dir`` into structured records.

    The manifest is used for ordering/metadata when available; orphan files
    (for example after a partial download) are still discovered on disk.
    """
    records: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    manifest_file = output_dir / "index.json"

    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = []
        if isinstance(manifest, list):
            for entry in manifest:
                if not isinstance(entry, dict):
                    continue
                filename = str(entry.get("file") or "")
                if not filename or filename in seen_files:
                    continue
                file_path = (output_dir / filename).resolve()
                if not file_path.is_relative_to(output_dir.resolve()) or not file_path.is_file():
                    continue
                seen_files.add(filename)
                file_records = _records_from_file(file_path)
                for record in file_records:
                    record.setdefault("depth", entry.get("depth", 0))
                    if entry.get("title"):
                        record.setdefault("title", entry["title"])
                records.extend(file_records)

    patterns = ("*.md", "*.txt", "*.json", "*.jsonl")
    for pattern in patterns:
        for file_path in sorted(output_dir.glob(pattern)):
            if not file_path.is_file() or file_path.name in seen_files or file_path.name in _SKIP_FILES:
                continue
            seen_files.add(file_path.name)
            records.extend(_records_from_file(file_path))

    return records


def _to_page_content(record: dict[str, Any]) -> PageContent:
    kwargs = {key: value for key, value in record.items() if key in _PAGE_FIELDS}
    page = PageContent(**kwargs)
    if not page.title:
        page.title = "Untitled page"
    if not page.text and page.markdown:
        page.text = _markdown_to_text(page.markdown)
    if not page.markdown and page.text:
        page.markdown = page.text
    return page


def _zip_paths(base_dir: Path, paths: Iterable[Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=str(path.relative_to(base_dir)))
    return buffer.getvalue()


def build_results_zip(output_dir: Path, target_format: str | None = None) -> bytes:
    """Return a ZIP payload for ``output_dir``.

    ``target_format`` of ``None`` keeps the files exactly as crawled. Otherwise
    every page is re-serialized in the requested format before zipping.
    """
    output_dir = output_dir.resolve()
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    if not files:
        raise FileNotFoundError("No files found in output directory to download.")

    normalized = normalize_format(target_format)
    if normalized is None:
        return _zip_paths(output_dir, files)

    records = parse_saved_pages(output_dir)
    if not records:
        # Nothing parseable (e.g. only logs) - fall back to the raw archive.
        return _zip_paths(output_dir, files)

    with TemporaryDirectory(prefix="web-scraper-export-") as temp_dir:
        export_dir = Path(temp_dir)
        writer = OutputWriter(str(export_dir), normalized)
        for record in records:
            depth = 0
            try:
                depth = int(record.get("depth", 0) or 0)
            except (TypeError, ValueError):
                depth = 0
            writer.save_document(_to_page_content(record), depth)
        writer.finalize()
        return _zip_paths(export_dir, [path for path in export_dir.rglob("*") if path.is_file()])
