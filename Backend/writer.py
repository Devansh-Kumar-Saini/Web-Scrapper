"""Output files, collision handling, and manifest writing."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from .extractor import PageContent
except ImportError:  # pragma: no cover - direct script execution
    from extractor import PageContent

OUTPUT_FORMATS = ("txt", "md", "json", "jsonl")
_SUFFIXES = {"txt": ".txt", "md": ".md", "json": ".json", "jsonl": ".jsonl"}
_JSONL_FILENAME = "pages.jsonl"


def _safe_stem(url: str) -> str:
    parsed = urlparse(url)
    raw = parsed.path.strip("/") or parsed.netloc
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return (stem or "page")[:96]


def _yaml_value(value: str) -> str:
    """Quote a string safely for YAML front matter."""
    return json.dumps(value, ensure_ascii=False)


class OutputWriter:
    def __init__(self, output_dir: str, output_format: str = "txt") -> None:
        self.output_format = (output_format or "txt").lower().strip()
        if self.output_format not in OUTPUT_FORMATS:
            raise ValueError(
                f"Unsupported output format '{output_format}'. Choose one of: {', '.join(OUTPUT_FORMATS)}"
            )
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: list[dict[str, object]] = []
        self._used_names: set[str] = set()
        self.files_written = 0
        self.written_files: set[str] = set()

        manifest_file = self.output_dir / "index.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.manifest = data
                    for item in data:
                        if isinstance(item, dict) and "file" in item:
                            self._used_names.add(str(item["file"]))
            except Exception:
                pass

    def _filename(self, url: str) -> str:
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

    def save_document(self, document: PageContent, depth: int) -> str:
        """Persist a structured page in the configured output format."""
        scraped_at = datetime.now(timezone.utc).isoformat()
        entry: dict[str, object] = {
            "url": document.url,
            "title": document.title,
            "depth": depth,
        }
        if self.output_format != "txt":
            entry["format"] = self.output_format
        byte_count = 0

        if self.output_format == "jsonl":
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
        self.manifest.append(entry)
        return filename

    def save_page(self, url: str, title: str, text: str, depth: int) -> str:
        """Backward-compatible helper for saving plain extracted text."""
        return self.save_document(PageContent(url=url, title=title, text=text), depth)

    def finalize(self) -> None:
        (self.output_dir / "index.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
        self.files_written += 1
        self.written_files.add("index.json")
