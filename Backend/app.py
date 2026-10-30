"""Flask server and REST/SSE API for the website scraper UI."""

from __future__ import annotations

import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from flask import Flask, Response, jsonify, request, send_file

# Support relative or package import
try:
    from .config import DEFAULT_MAX_PAGES, MAX_DEPTH
    from .crawler import Crawler
    from .extractor import extract_structured, validate_selectors
    from .fetcher import FetchError, NonHtmlContent, RobotsDisallowed
    from .filters import parse_patterns, parse_selectors
    from .scraper import scrape_url
    from .writer import OUTPUT_FORMATS, OutputWriter
except ImportError:
    from config import DEFAULT_MAX_PAGES, MAX_DEPTH
    from crawler import Crawler
    from extractor import extract_structured, validate_selectors
    from fetcher import FetchError, NonHtmlContent, RobotsDisallowed
    from filters import parse_patterns, parse_selectors
    from scraper import scrape_url
    from writer import OUTPUT_FORMATS, OutputWriter

# Determine project root and UI directory
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
UI_DIR = PROJECT_ROOT / "UI"

app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")


def _valid_url(value: str) -> str | None:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return None


def _parse_urls(values: list[str]) -> tuple[list[str], list[str]]:
    valid, invalid = [], []
    for value in values:
        # Support comma-separated or newline-separated strings
        for item in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            for sub in item.split(","):
                cand = sub.strip()
                if not cand:
                    continue
                if _valid_url(cand):
                    valid.append(cand)
                else:
                    invalid.append(cand)
    return list(dict.fromkeys(valid)), invalid


def _resolve_output_dir(raw: str) -> Path:
    """Normalize a user-provided output directory string to an absolute Path."""
    cleaned = (raw or "./output").strip() or "./output"
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "n"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_output_format(value: Any) -> str | None:
    """Accept both CLI (txt/md) and API-friendly (text/markdown) format names."""
    fmt = str(value or "txt").strip().lower()
    aliases = {"text": "txt", "markdown": "md", "jsonl": "jsonl", "json": "json", "md": "md", "txt": "txt"}
    fmt = aliases.get(fmt, fmt)
    return fmt if fmt in OUTPUT_FORMATS else None


def _pick_folder_native() -> tuple[bool, str, str]:
    """Open the OS folder chooser.

    Returns ``(canceled, path, error)``. The dialog is shown by the machine that
    runs the Flask server, which is normally the same machine as the browser.
    """
    timeout = 300

    try:
        if sys.platform == "darwin":
            script = 'POSIX path of (choose folder with prompt "Select a folder for scraped output")'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout,
            )
            stderr = (result.stderr or "").strip()
            if result.returncode != 0:
                if "(-128)" in stderr or "user canceled" in stderr.lower():
                    return True, "", ""
                return False, "", stderr or "Folder picker failed to open."
            # AppleScript returns a POSIX path with a trailing slash.
            return False, result.stdout.strip().rstrip("/") or "/", ""

        if sys.platform.startswith("win"):
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$f.Description = 'Select a folder for scraped output'; "
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps_script],
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                return False, "", (result.stderr or "").strip() or "Folder picker failed to open."
            path = result.stdout.strip()
            return (False, path, "") if path else (True, "", "")

        # Linux: prefer native GTK/Qt dialogs when available.
        for cmd in (
            ["zenity", "--file-selection", "--directory", "--title=Select a folder for scraped output"],
            ["kdialog", "--getexistingdirectory", str(Path.home())],
        ):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except FileNotFoundError:
                continue
            if result.returncode == 0:
                path = result.stdout.strip()
                return (False, path, "") if path else (True, "", "")
            return True, "", ""
        return False, "", "No supported folder dialog found (install zenity or kdialog)."
    except FileNotFoundError:
        return False, "", "System folder picker is not available on this machine."
    except subprocess.TimeoutExpired:
        return True, "", ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, "", f"Could not open folder picker: {exc}"


@dataclass
class JobState:
    status: str = "idle"  # idle, running, stopping, completed, failed
    urls: list[str] = field(default_factory=list)
    depth: int = 1
    max_pages: int = DEFAULT_MAX_PAGES
    same_domain: bool = True
    output_dir: str = "./output"
    output_format: str = "txt"
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    target_selector: str = ""
    exclude_selectors: list[str] = field(default_factory=list)
    chunk_size: int = 0
    chunk_overlap: int = 400
    respect_robots: bool = True
    concurrency: int = 5
    sitemap: bool = False
    sitemap_url: str = ""
    impersonate: str = "chrome"
    proxy: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    elapsed_seconds: float = 0.0
    pages_crawled: int = 0
    pages_saved: int = 0
    pages_skipped: int = 0
    current_url: str = ""
    current_depth: int = 0
    error_message: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    recent_pages: list[dict[str, Any]] = field(default_factory=list)


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.state = JobState()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.subscribers: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self.lock:
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for d in dead:
                if d in self.subscribers:
                    self.subscribers.remove(d)

    def log(self, level: str, message: str) -> None:
        entry = {
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": level.upper(),
            "message": message,
        }
        with self.lock:
            self.state.logs.append(entry)
            if len(self.state.logs) > 500:
                self.state.logs.pop(0)
        self.broadcast("log", entry)

    def get_snapshot(self) -> dict[str, Any]:
        with self.lock:
            elapsed = 0.0
            if self.state.started_at:
                if self.state.finished_at:
                    elapsed = self.state.finished_at - self.state.started_at
                else:
                    elapsed = time.monotonic() - self.state.started_at
            data = asdict(self.state)
            data["elapsed_seconds"] = round(elapsed, 2)
            return data

    def reset(self) -> None:
        with self.lock:
            if self.state.status == "running":
                self.stop_event.set()
            self.state = JobState()
        snap = self.get_snapshot()
        self.broadcast("reset", snap)
        self.broadcast("status", snap)
        self.broadcast("stats", snap)

    def start_crawl(
        self,
        urls: list[str],
        depth: int,
        max_pages: int,
        same_domain: bool,
        output_dir: str,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        target_selector: str = "",
        exclude_selectors: list[str] | None = None,
        output_format: str = "txt",
        chunk_size: int = 0,
        chunk_overlap: int = 400,
        respect_robots: bool = True,
        concurrency: int = 5,
        sitemap: bool = False,
        sitemap_url: str = "",
        impersonate: str | None = "chrome",
        proxy: str | None = None,
    ) -> tuple[bool, str]:
        with self.lock:
            if self.state.status in {"running", "stopping"}:
                return False, "A crawling job is already running."

            self.stop_event.clear()
            self.state = JobState(
                status="running",
                urls=urls,
                depth=depth,
                max_pages=max_pages,
                same_domain=same_domain,
                output_dir=output_dir,
                output_format=output_format,
                include_patterns=parse_patterns(include_patterns),
                exclude_patterns=parse_patterns(exclude_patterns),
                target_selector=target_selector,
                exclude_selectors=parse_selectors(exclude_selectors),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                respect_robots=respect_robots,
                concurrency=concurrency,
                sitemap=sitemap,
                sitemap_url=sitemap_url,
                impersonate=impersonate or "chrome",
                proxy=proxy or "",
                started_at=time.monotonic(),
            )

        self.worker_thread = threading.Thread(
            target=self._run_crawler_worker,
            args=(
                urls,
                depth,
                max_pages,
                same_domain,
                output_dir,
                parse_patterns(include_patterns),
                parse_patterns(exclude_patterns),
                target_selector,
                parse_selectors(exclude_selectors),
                output_format,
                chunk_size,
                chunk_overlap,
                respect_robots,
                concurrency,
                sitemap,
                sitemap_url,
                impersonate,
                proxy,
            ),
            daemon=True,
        )
        self.worker_thread.start()
        self.broadcast("status", self.get_snapshot())
        return True, "Crawl job started."

    def stop_crawl(self) -> tuple[bool, str]:
        with self.lock:
            if self.state.status != "running":
                return False, "No active crawl to stop."
            self.state.status = "stopping"
            self.stop_event.set()

        self.log("WARN", "Stopping crawler on user request...")
        self.broadcast("status", self.get_snapshot())
        return True, "Stop signal sent."

    def _run_crawler_worker(
        self,
        urls: list[str],
        depth: int,
        max_pages: int,
        same_domain: bool,
        output_dir_str: str,
        include_patterns: list[str],
        exclude_patterns: list[str],
        target_selector: str,
        exclude_selectors: list[str],
        output_format: str,
        chunk_size: int,
        chunk_overlap: int,
        respect_robots: bool,
        concurrency: int = 5,
        sitemap: bool = False,
        sitemap_url: str = "",
        impersonate: str | None = "chrome",
        proxy: str | None = None,
    ) -> None:
        out_path = _resolve_output_dir(output_dir_str)
        out_path.mkdir(parents=True, exist_ok=True)

        log_path = out_path / "scrape_log.txt"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger = logging.getLogger(f"scraper_{time.time()}")
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)

        class UIBridgeLogHandler(logging.Handler):
            def __init__(self, manager: JobManager) -> None:
                super().__init__()
                self.manager = manager

            def emit(self, record: logging.LogRecord) -> None:
                self.manager.log(record.levelname, record.getMessage())

        ui_handler = UIBridgeLogHandler(self)
        logger.addHandler(ui_handler)

        self.log("INFO", f"Starting scrape for {len(urls)} seed URL(s) to {output_dir_str}")
        self.log(
            "INFO",
            f"Settings: depth={depth}, max_pages={max_pages}, same_domain={same_domain}, "
            f"format={output_format}, include={include_patterns or 'any'}, exclude={exclude_patterns or 'none'}",
        )
        if target_selector:
            self.log("INFO", f"Target selector: {target_selector}")
        if exclude_selectors:
            self.log("INFO", f"Excluding selectors: {', '.join(exclude_selectors)}")

        writer = OutputWriter(str(out_path), output_format=output_format)
        crawler = Crawler(
            max_depth=depth,
            max_pages=max_pages,
            same_domain=same_domain,
            logger=logger,
            stop_event=self.stop_event,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            respect_robots=respect_robots,
            concurrency=concurrency,
            sitemap=sitemap,
            sitemap_url=sitemap_url,
            impersonate=impersonate,
            proxy=proxy,
        )

        try:
            try:
                for page in crawler.crawl(urls):
                    if self.stop_event.is_set():
                        break

                    with self.lock:
                        self.state.current_url = page.url
                        self.state.current_depth = page.depth
                        self.state.pages_crawled += 1

                    try:
                        document = extract_structured(
                            page.html,
                            url=page.url,
                            target_selector=target_selector or None,
                            exclude_selectors=exclude_selectors,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                        )
                    except Exception as exc:
                        crawler.skipped_reasons.append(f"extraction failure: {page.url}")
                        self.log("WARN", f"Extraction failed for {page.url}: {exc}")
                        continue

                    filename = writer.save_document(document, page.depth)
                    title = document.title
                    file_size = (out_path / filename).stat().st_size

                    page_info = {
                        "file": filename,
                        "url": page.url,
                        "title": title,
                        "depth": page.depth,
                        "bytes": file_size,
                        "format": output_format,
                        "saved_at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    }

                    with self.lock:
                        self.state.pages_saved += 1
                        self.state.recent_pages.append(page_info)
                        if len(self.state.recent_pages) > 300:
                            self.state.recent_pages.pop(0)

                    self.log("INFO", f"[depth {page.depth}] Saved {page.url} -> {filename} ({file_size} bytes)")
                    self.broadcast("page_saved", page_info)
                    self.broadcast("stats", self.get_snapshot())
            finally:
                writer.finalize()

            stopped = self.stop_event.is_set()
            saved_count = 0
            with self.lock:
                self.state.pages_skipped = len(crawler.skipped_reasons)
                self.state.finished_at = time.monotonic()
                self.state.status = "completed"
                saved_count = self.state.pages_saved

            if stopped:
                self.log("WARN", "Crawl stopped by user. Manifest saved.")
            else:
                self.log("INFO", f"Crawl completed successfully! Saved {saved_count} pages.")
        except Exception as exc:
            logger.exception("Crawl encountered an unhandled exception")
            with self.lock:
                self.state.status = "failed"
                self.state.finished_at = time.monotonic()
                self.state.error_message = str(exc)
            self.log("ERROR", f"Fatal error during crawl: {exc}")
        finally:
            logger.removeHandler(file_handler)
            logger.removeHandler(ui_handler)
            file_handler.close()
            with self.lock:
                self.state.current_url = ""
            self.broadcast("status", self.get_snapshot())


job_manager = JobManager()


# --- UI & Static Routes ---

@app.route("/")
def index() -> Any:
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return send_file(index_file)
    return "UI index.html not found.", 404


@app.route("/<path:path>")
def static_files(path: str) -> Any:
    file_path = (UI_DIR / path).resolve()
    if file_path.is_file() and str(file_path).startswith(str(UI_DIR.resolve())):
        return send_file(file_path)
    return "File not found", 404


# --- REST API Endpoints ---

@app.route("/api/system/pick-folder", methods=["POST"])
def api_pick_folder() -> Any:
    """Open the host machine's native folder picker and return the chosen path."""
    if os.environ.get("RENDER") or os.environ.get("DYNO"):
        return jsonify({
            "is_cloud": True,
            "path": "./output",
            "message": "Folder selection is disabled on cloud deployments. Output files are saved to './output' and can be downloaded using the 'Download ZIP' button below."
        }), 200

    canceled, path, error = _pick_folder_native()
    if canceled:
        return jsonify({"canceled": True})
    if error or not path:
        return jsonify({"error": error or "No folder was selected."}), 500

    folder = _resolve_output_dir(path)
    if not folder.is_dir():
        return jsonify({"error": "Selected location is not a directory."}), 400
    return jsonify({"canceled": False, "path": str(folder)})


@app.route("/api/scrape", methods=["GET", "POST"])
def api_scrape() -> Any:
    """Scrape a single URL synchronously and return Markdown, text, HTML, or JSON.

    Example:
        curl -X POST http://localhost:5000/api/scrape \\
          -H "Content-Type: application/json" \\
          -d '{"url": "https://example.com", "format": "markdown"}'
    """
    if request.method == "GET":
        data: dict[str, Any] = request.args.to_dict()
    else:
        data = request.get_json(silent=True) or request.form.to_dict() or {}

    url = _valid_url(str(data.get("url", "")))
    if not url:
        return jsonify({"error": "A valid HTTP/HTTPS 'url' is required."}), 400

    output_format = str(data.get("format", "markdown")).strip().lower()
    format_aliases = {
        "markdown": "markdown",
        "md": "markdown",
        "text": "text",
        "txt": "text",
        "json": "json",
        "html": "html",
    }
    output_format = format_aliases.get(output_format, output_format)
    if output_format not in {"markdown", "text", "json", "html"}:
        return jsonify({"error": "format must be one of: markdown, text, html, json."}), 400

    target_selector = str(data.get("selector") or data.get("target_selector") or "").strip() or None
    exclude_selectors = parse_selectors(data.get("exclude_selectors", data.get("exclude_selector")))
    chunk_size = _as_int(data.get("chunk_size", 0), 0)
    chunk_overlap = _as_int(data.get("chunk_overlap", 400), 400)
    if chunk_size < 0 or chunk_overlap < 0:
        return jsonify({"error": "chunk_size and chunk_overlap cannot be negative."}), 400

    impersonate = data.get("impersonate", "chrome")
    if impersonate == "none":
        impersonate = None
    proxy = str(data.get("proxy") or "").strip() or None

    try:
        document = scrape_url(
            url,
            render_js=_as_bool(data.get("render_js"), False),
            target_selector=target_selector,
            exclude_selectors=exclude_selectors,
            respect_robots=_as_bool(data.get("respect_robots"), True),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            impersonate=impersonate,
            proxy=proxy,
            logger=app.logger,
        )
    except RobotsDisallowed as exc:
        return jsonify({"error": f"Blocked by robots.txt: {exc.url}", "url": exc.url, "code": "robots_disallowed"}), 403
    except NonHtmlContent as exc:
        return jsonify({"error": str(exc), "url": exc.url, "code": "non_html"}), 415
    except FetchError as exc:
        timed_out = exc.status_code == 504 or "timeout" in str(exc).lower() or "timed out" in str(exc).lower()
        status = 504 if timed_out else 502
        return jsonify({"error": str(exc), "url": exc.url, "code": "timeout" if timed_out else "fetch_failed"}), status
    except ValueError as exc:
        return jsonify({"error": f"Invalid selector: {exc}"}), 400
    except Exception as exc:  # pragma: no cover - defensive
        app.logger.exception("Single-URL scrape failed for %s", url)
        return jsonify({"error": f"Scrape failed: {exc}"}), 500

    if output_format == "json":
        response = jsonify(document.to_dict())
    else:
        if output_format == "markdown":
            body, mimetype = document.markdown or document.text, "text/markdown"
        elif output_format == "html":
            # Serve as plain text so browsers never execute scraped markup.
            body, mimetype = document.html, "text/plain"
        else:
            body, mimetype = document.text, "text/plain"
        response = Response(body, mimetype=mimetype)

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Scraped-URL"] = quote(document.url, safe="")
    response.headers["X-Word-Count"] = str(document.word_count)
    if not document.selector_matched:
        response.headers["X-Selector-Matched"] = "false"
    return response


@app.route("/api/scrape/start", methods=["POST"])
def api_scrape_start() -> Any:
    data = request.get_json(silent=True) or {}
    raw_urls = data.get("urls", [])
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]

    valid_urls, invalid_urls = _parse_urls(raw_urls)
    if not valid_urls:
        return jsonify({"error": "No valid HTTP/HTTPS URLs provided.", "invalid": invalid_urls}), 400

    try:
        depth = int(data.get("depth", 1))
        if depth < 0 or depth > MAX_DEPTH:
            return jsonify({"error": f"Depth must be between 0 and {MAX_DEPTH}."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Depth must be an integer."}), 400

    try:
        max_pages = int(data.get("max_pages", DEFAULT_MAX_PAGES))
        if max_pages < 1:
            return jsonify({"error": "Max pages must be at least 1."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Max pages must be an integer."}), 400

    same_domain = _as_bool(data.get("same_domain"), True)
    output_dir = str(data.get("output_dir", "./output")).strip() or "./output"

    include_patterns = parse_patterns(data.get("include_patterns", data.get("include_pattern")))
    exclude_patterns = parse_patterns(data.get("exclude_patterns", data.get("exclude_pattern")))
    target_selector = str(data.get("selector") or data.get("target_selector") or "").strip()
    exclude_selectors = parse_selectors(data.get("exclude_selectors", data.get("exclude_selector")))
    try:
        validate_selectors(target_selector or None, exclude_selectors)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    output_format = _normalize_output_format(data.get("format", data.get("output_format", "txt")))
    if output_format is None:
        return jsonify({"error": f"Format must be one of: {', '.join(OUTPUT_FORMATS)} (or text/markdown)."}), 400

    chunk_size = _as_int(data.get("chunk_size", 0), 0)
    if chunk_size < 0:
        return jsonify({"error": "chunk_size cannot be negative."}), 400
    chunk_overlap = _as_int(data.get("chunk_overlap", 400), 400)
    if chunk_overlap < 0:
        return jsonify({"error": "chunk_overlap cannot be negative."}), 400

    respect_robots = _as_bool(data.get("respect_robots"), True)
    concurrency = _as_int(data.get("concurrency", 5), 5)
    sitemap = _as_bool(data.get("sitemap"), False)
    sitemap_url = str(data.get("sitemap_url") or "").strip()
    impersonate = data.get("impersonate", "chrome")
    if impersonate == "none":
        impersonate = None
    proxy = str(data.get("proxy") or "").strip() or None

    started, msg = job_manager.start_crawl(
        urls=valid_urls,
        depth=depth,
        max_pages=max_pages,
        same_domain=same_domain,
        output_dir=output_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        target_selector=target_selector,
        exclude_selectors=exclude_selectors,
        output_format=output_format,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        respect_robots=respect_robots,
        concurrency=concurrency,
        sitemap=sitemap,
        sitemap_url=sitemap_url,
        impersonate=impersonate,
        proxy=proxy,
    )

    if not started:
        return jsonify({"error": msg}), 409

    return jsonify({
        "status": "started",
        "message": msg,
        "valid_urls": valid_urls,
        "invalid_urls": invalid_urls,
        "config": {
            "depth": depth,
            "max_pages": max_pages,
            "same_domain": same_domain,
            "output_dir": output_dir,
            "format": output_format,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "target_selector": target_selector,
            "exclude_selectors": exclude_selectors,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "respect_robots": respect_robots,
            "concurrency": concurrency,
            "sitemap": sitemap,
            "sitemap_url": sitemap_url,
            "impersonate": impersonate,
            "proxy": proxy,
        },
    })


@app.route("/api/scrape/stop", methods=["POST"])
def api_scrape_stop() -> Any:
    stopped, msg = job_manager.stop_crawl()
    if not stopped:
        return jsonify({"error": msg}), 400
    return jsonify({"status": "stopping", "message": msg})


@app.route("/api/scrape/status", methods=["GET"])
def api_scrape_status() -> Any:
    return jsonify(job_manager.get_snapshot())


@app.route("/api/scrape/reset", methods=["POST"])
def api_scrape_reset() -> Any:
    job_manager.reset()
    return jsonify({"status": "reset", "snapshot": job_manager.get_snapshot()})


@app.route("/api/scrape/events", methods=["GET"])
def api_scrape_events() -> Response:
    q = job_manager.subscribe()

    def stream() -> Any:
        # Send initial snapshot immediately upon connection
        init_data = json.dumps(job_manager.get_snapshot())
        yield f"event: init\ndata: {init_data}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=10.0)
                    yield msg
                except queue.Empty:
                    # SSE keep-alive ping
                    yield ": ping\n\n"
        except GeneratorExit:
            job_manager.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/results", methods=["GET"])
def api_results() -> Any:
    out_path = _resolve_output_dir(request.args.get("output_dir", "./output"))

    if not out_path.exists() or not out_path.is_dir():
        return jsonify({"pages": [], "total_pages": 0, "total_bytes": 0, "has_manifest": False})

    manifest_file = out_path / "index.json"
    pages = []
    has_manifest = False

    if manifest_file.exists():
        try:
            pages = json.loads(manifest_file.read_text(encoding="utf-8"))
            has_manifest = True
        except Exception:
            pages = []

    # If manifest is empty or missing, scan for saved page files.
    if not pages:
        seen_names: set[str] = set()
        for pattern in ("*.txt", "*.md", "*.json", "*.jsonl"):
            for f in sorted(out_path.glob(pattern)):
                if f.name in {"scrape_log.txt", "index.json"} or f.name in seen_names:
                    continue
                seen_names.add(f.name)
                pages.append({
                    "file": f.name,
                    "url": "",
                    "title": f.stem.replace("_", " ").title(),
                    "depth": 0,
                    "bytes": f.stat().st_size,
                    "format": f.suffix.lstrip("."),
                })

    total_bytes = sum(p.get("bytes", 0) for p in pages)
    return jsonify({
        "output_dir": str(out_path),
        "pages": pages,
        "total_pages": len(pages),
        "total_bytes": total_bytes,
        "has_manifest": has_manifest,
    })


@app.route("/api/results/file", methods=["GET"])
def api_results_file() -> Any:
    filename = request.args.get("file", "").strip()
    if not filename:
        return jsonify({"error": "Missing file parameter."}), 400

    out_path = _resolve_output_dir(request.args.get("output_dir", "./output"))
    target_file = (out_path / filename).resolve()
    # Path traversal protection
    if not target_file.is_relative_to(out_path):
        return jsonify({"error": "Forbidden: Path traversal detected."}), 403

    if not target_file.exists() or not target_file.is_file():
        return jsonify({"error": "File not found."}), 404

    try:
        content = target_file.read_text(encoding="utf-8", errors="replace")
        stat = target_file.stat()
        return jsonify({
            "file": target_file.name,
            "bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "content": content,
            "lines": len(content.splitlines()),
        })
    except Exception as exc:
        return jsonify({"error": f"Failed to read file: {exc}"}), 500


@app.route("/api/results/download", methods=["GET"])
def api_results_download() -> Any:
    out_path = _resolve_output_dir(request.args.get("output_dir", "./output"))

    if not out_path.exists() or not out_path.is_dir():
        return jsonify({"error": "Output directory does not exist."}), 404

    file_count = 0
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root_dir, _, files in os.walk(out_path):
            for file in files:
                file_full = Path(root_dir) / file
                rel_path = file_full.relative_to(out_path)
                zf.write(file_full, arcname=str(rel_path))
                file_count += 1

    if file_count == 0:
        return jsonify({"error": "No files found in output directory to download."}), 404

    zip_buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"scraped_pages_{timestamp}.zip",
    )


@app.route("/api/results/clear", methods=["POST"])
def api_results_clear() -> Any:
    data = request.get_json(silent=True) or {}
    out_path = _resolve_output_dir(str(data.get("output_dir", "./output")))

    deleted = 0
    if out_path.exists() and out_path.is_dir():
        for item in sorted(out_path.glob("**/*"), key=lambda p: len(str(p)), reverse=True):
            if item.is_file():
                try:
                    item.unlink()
                    deleted += 1
                except OSError:
                    pass
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass

    job_manager.reset()
    return jsonify({"status": "cleared", "deleted_files": deleted})


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    print("\n=======================================================")
    print("  Website Scraper UI Server running at:")
    print(f"  --> http://{host}:{port}")
    print("=======================================================\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Website Scraper Web UI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, debug=args.debug)
