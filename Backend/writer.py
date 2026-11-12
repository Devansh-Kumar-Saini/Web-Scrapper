"""Output files, collision handling, and manifest writing."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .extractor import PageContent
except ImportError:  # pragma: no cover - direct script execution
    from extractor import PageContent

OUTPUT_FORMATS = ("txt", "md", "json", "jsonl", "csv", "sqlite")
_SUFFIXES = {"txt": ".txt", "md": ".md", "json": ".json", "jsonl": ".jsonl"}
_JSONL_FILENAME = "pages.jsonl"
_CSV_FILENAME = "pages.csv"
_SQLITE_FILENAME = "pages.db"

# Shared column order for CSV rows and the SQLite ``pages`` table.
_ROW_FIELDS = (
    "url",
    "title",
    "description",
    "author",
    "published_time",
    "canonical_url",
    "depth",
    "scraped_at",
    "status_code",
    "word_count",
    "selector_matched",
    "text",
    "markdown",
    "html",
    "links",
    "images",
    "headings",
    "chunks",
    "schema",
)

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    title TEXT,
    description TEXT,
    author TEXT,
    published_time TEXT,
    canonical_url TEXT,
    depth INTEGER,
    scraped_at TEXT,
    status_code INTEGER,
    word_count INTEGER,
    selector_matched INTEGER,
    text TEXT,
    markdown TEXT,
    html TEXT,
    links TEXT,
    images TEXT,
    headings TEXT,
    chunks TEXT,
    schema TEXT
)
"""


def _document_row(document: PageContent, depth: int, scraped_at: str) -> dict[str, Any]:
    """Flatten a document into one CSV/SQLite row (lists stored as JSON)."""
    return {
        "url": document.url,
        "title": document.title,
        "description": document.description,
        "author": document.author,
        "published_time": document.published_time,
        "canonical_url": document.canonical_url,
        "depth": depth,
        "scraped_at": scraped_at,
        "status_code": document.status_code,
        "word_count": document.word_count,
        "selector_matched": int(bool(document.selector_matched)),
        "text": document.text,
        "markdown": document.markdown,
        "html": document.html,
        "links": json.dumps(document.links, ensure_ascii=False),
        "images": json.dumps(document.images, ensure_ascii=False),
        "headings": json.dumps(document.headings, ensure_ascii=False),
        "chunks": json.dumps(document.chunks, ensure_ascii=False),
        "schema": json.dumps(document.schema, ensure_ascii=False),
    }


def _safe_stem(url: str) -> str:
    parsed = urlparse(url)
    raw = parsed.path.strip("/") or parsed.netloc
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return (stem or "page")[:96]


def _yaml_value(value: str) -> str:
    """Quote a string safely for YAML front matter."""
    return json.dumps(value, ensure_ascii=False)


class OutputWriter:
    def __init__(
        self,
        output_dir: str,
        output_format: str = "txt",
        media_only: bool = False,
        incremental: bool = False,
    ) -> None:
        self.output_format = (output_format or "txt").lower().strip()
        self.media_only = bool(media_only)
        self.incremental = bool(incremental)
        if self.output_format not in OUTPUT_FORMATS:
            raise ValueError(
                f"Unsupported output format '{output_format}'. Choose one of: {', '.join(OUTPUT_FORMATS)}"
            )
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: list[dict[str, object]] = []
        self._used_names: set[str] = set()
        self._url_entries: dict[str, dict[str, object]] = {}
        self.files_written = 0
        self.written_files: set[str] = set()
        self._sqlite_connection: sqlite3.Connection | None = None

        manifest_file = self.output_dir / "index.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.manifest = data
                    for item in data:
                        if isinstance(item, dict) and "file" in item:
                            self._used_names.add(str(item["file"]))
                            url = str(item.get("url") or "")
                            if url:
                                self._url_entries[url] = item
            except Exception:
                pass

    def _filename(self, url: str) -> str:
        if self.incremental:
            existing = self._url_entries.get(url)
            if existing and existing.get("file"):
                filename = str(existing["file"])
                self._used_names.add(filename)
                return filename
        stem = _safe_stem(url)
        suffix = _SUFFIXES[self.output_format]
        candidate = f"{stem}{suffix}"
        counter = 2
        while candidate in self._used_names or (self.output_dir / candidate).exists():
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1
        self._used_names.add(candidate)
        return candidate

    def _write_text(self, filename: str, content: str) -> Path:
        path = self.output_dir / filename
        path.write_text(content, encoding="utf-8")
        self.files_written += 1
        return path

    def _save_csv(self, document: PageContent, depth: int, scraped_at: str) -> tuple[str, int]:
        path = self.output_dir / _CSV_FILENAME
        before = path.stat().st_size if path.exists() else 0
        row = _document_row(document, depth, scraped_at)
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_ROW_FIELDS)
            if before == 0:
                writer.writeheader()
            writer.writerow(row)
        self.files_written += 1
        self.written_files.add(_CSV_FILENAME)
        return _CSV_FILENAME, path.stat().st_size - before

    def _get_sqlite(self) -> sqlite3.Connection:
        if self._sqlite_connection is None:
            connection = sqlite3.connect(self.output_dir / _SQLITE_FILENAME)
            connection.execute(_SQLITE_SCHEMA)
            connection.commit()
            self._sqlite_connection = connection
        return self._sqlite_connection

    def _save_sqlite(self, document: PageContent, depth: int, scraped_at: str) -> tuple[str, int]:
        path = self.output_dir / _SQLITE_FILENAME
        before = path.stat().st_size if path.exists() else 0
        row = _document_row(document, depth, scraped_at)
        connection = self._get_sqlite()
        columns = ", ".join(_ROW_FIELDS)
        placeholders = ", ".join("?" for _ in _ROW_FIELDS)
        connection.execute(
            f"INSERT INTO pages ({columns}) VALUES ({placeholders})",
            [row[field] for field in _ROW_FIELDS],
        )
        connection.commit()
        self.files_written += 1
        self.written_files.add(_SQLITE_FILENAME)
        return _SQLITE_FILENAME, path.stat().st_size - before

    def save_document(self, document: PageContent, depth: int) -> str:
        """Persist a structured page in the configured output format."""
        scraped_at = datetime.now(timezone.utc).isoformat()
        entry: dict[str, object] = {
            "url": document.url,
            "title": document.title,
            "depth": depth,
        }
        if self.media_only:
            entry["mode"] = "media_only"
            self.manifest.append(entry)
            self._flush_manifest()
            return ""

        if self.output_format != "txt":
            entry["format"] = self.output_format
        byte_count = 0

        if self.output_format == "csv":
            filename, byte_count = self._save_csv(document, depth, scraped_at)
        elif self.output_format == "sqlite":
            filename, byte_count = self._save_sqlite(document, depth, scraped_at)
        elif self.output_format == "jsonl":
            filename = _JSONL_FILENAME
            record = document.to_dict()
            record.update({"depth": depth, "scraped_at": scraped_at})
            line = json.dumps(record, ensure_ascii=False) + "\n"
            path = self.output_dir / filename
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                byte_count = len(line.encode("utf-8"))
            self.files_written += 1
            self.written_files.add(filename)
        else:
            filename = self._filename(document.url)
            if self.output_format == "txt":
                body = document.text or "[No text content extracted]"
                content = (
                    f"Title: {document.title}\n"
                    f"URL: {document.url}\n"
                    f"Depth: {depth}\n"
                    f"Scraped: {scraped_at}\n\n"
                    "----------------------------------------\n\n"
                    f"{body}\n"
                )
            elif self.output_format == "md":
                front_matter = [
                    "---",
                    f"title: {_yaml_value(document.title)}",
                    f"url: {_yaml_value(document.url)}",
                    f"depth: {depth}",
                    f"scraped_at: {_yaml_value(scraped_at)}",
                ]
                if document.description:
                    front_matter.append(f"description: {_yaml_value(document.description)}")
                if document.author:
                    front_matter.append(f"author: {_yaml_value(document.author)}")
                if document.published_time:
                    front_matter.append(f"published_time: {_yaml_value(document.published_time)}")
                front_matter.append("---")
                body = document.markdown or document.text or "_No text content extracted._"
                content = "\n".join(front_matter) + f"\n\n{body}\n"
            else:  # json
                record = document.to_dict()
                record.update({"depth": depth, "scraped_at": scraped_at})
                content = json.dumps(record, ensure_ascii=False, indent=2) + "\n"

            path = self._write_text(filename, content)
            byte_count = path.stat().st_size
            self.written_files.add(filename)

        entry.update({"file": filename, "bytes": byte_count})
        if document.description:
            entry["description"] = document.description
        if document.word_count:
            entry["word_count"] = document.word_count
        if self.incremental:
            existing = self._url_entries.get(document.url)
            if existing is not None:
                try:
                    index = self.manifest.index(existing)
                    self.manifest[index] = entry
                except ValueError:
                    self.manifest.append(entry)
            else:
                self.manifest.append(entry)
            self._url_entries[document.url] = entry
        else:
            self.manifest.append(entry)
        self._flush_manifest()
        return filename

    def _flush_manifest(self) -> None:
        try:
            (self.output_dir / "index.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

    def save_page(self, url: str, title: str, text: str, depth: int) -> str:
        """Backward-compatible helper for saving plain extracted text."""
        return self.save_document(PageContent(url=url, title=title, text=text), depth)

    def finalize(self) -> None:
        if self._sqlite_connection is not None:
            try:
                self._sqlite_connection.commit()
                self._sqlite_connection.close()
            finally:
                self._sqlite_connection = None
        self._flush_manifest()
        self.files_written += 1
        self.written_files.add("index.json")
