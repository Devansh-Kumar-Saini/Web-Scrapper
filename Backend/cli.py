"""Command-line interface for the website scraper."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .config import DEFAULT_MAX_PAGES, MAX_DEPTH, REQUEST_DELAY_SECONDS
    from .crawler import Crawler
    from .extractor import _DEFAULT_CHUNK_OVERLAP, extract_structured, parse_schema, validate_selectors
    from .filters import parse_patterns, parse_selectors
    from .media import MediaCollector, parse_media_types
    from .sitemap import discover_sitemap_urls, fetch_sitemap_urls
    from .state import CrawlStore, DeltaCache, default_state_path
    from .webhook import notify, validate_webhook_url
    from .writer import _ROW_FIELDS, OUTPUT_FORMATS, OutputWriter, _document_row
except ImportError:  # pragma: no cover - direct script execution
    from config import DEFAULT_MAX_PAGES, MAX_DEPTH, REQUEST_DELAY_SECONDS
    from crawler import Crawler
    from extractor import _DEFAULT_CHUNK_OVERLAP, extract_structured, parse_schema, validate_selectors
    from filters import parse_patterns, parse_selectors
    from media import MediaCollector, parse_media_types
    from sitemap import discover_sitemap_urls, fetch_sitemap_urls
    from state import CrawlStore, DeltaCache, default_state_path
    from webhook import notify, validate_webhook_url
    from writer import _ROW_FIELDS, OUTPUT_FORMATS, OutputWriter, _document_row


def _load_config_file(explicit_path: str | None = None) -> dict[str, Any]:
    """Load configuration presets from a JSON config file."""
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser().resolve())
    else:
        candidates.append(Path(".scraperrc").resolve())
        candidates.append(Path("scraper.json").resolve())
        candidates.append(Path.home() / ".scraperrc")

    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as exc:
                sys.stderr.write(f"Warning: Failed to parse config file {candidate}: {exc}\n")
    return {}


def _load_schema(raw: str | None, path: str | None) -> dict[str, Any]:
    """Load a schema selector map from inline JSON or a JSON file."""
    if path:
        try:
            content = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"could not read schema file: {exc}") from exc
        try:
            return parse_schema(json.loads(content))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid schema file: {exc}") from exc
    return parse_schema(raw)


def _valid_url(value: str) -> str | None:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return None


def _parse_urls(values: list[str]) -> tuple[list[str], list[str]]:
    valid, invalid = [], []
    for value in values:
        for item in value.split(","):
            if _valid_url(item):
                valid.append(item.strip())
            elif item.strip():
                invalid.append(item.strip())
    return list(dict.fromkeys(valid)), invalid


def _ask(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _interactive(args: argparse.Namespace) -> argparse.Namespace:
    raw_urls = input("URL(s), comma-separated: ")
    args.url = [raw_urls]
    args.depth = int(_ask(f"Depth (0-{MAX_DEPTH})", str(args.depth)))
    args.max_pages = int(_ask("Max pages", str(args.max_pages)))
    args.same_domain = _ask("Same domain only? [Y/n]", "y").lower() not in {"n", "no"}
    args.output_dir = _ask("Output directory", args.output_dir)
    args.format = _ask(f"Output format ({'/'.join(OUTPUT_FORMATS)})", args.format)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl websites and save clean text, Markdown, JSON, JSONL, CSV, or SQLite locally."
    )
    parser.add_argument("--url", action="append", help="URL, repeat the flag or separate URLs with commas")
    parser.add_argument("--depth", type=int, choices=range(MAX_DEPTH + 1), default=1)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="txt",
        help="Output format: txt (default), md, json, jsonl, csv, or sqlite",
    )
    parser.add_argument(
        "--include-pattern",
        action="append",
        metavar="PATTERN",
        help="Only follow URLs matching this glob (or 're:' regex). Repeatable.",
    )
    parser.add_argument(
        "--exclude-pattern",
        action="append",
        metavar="PATTERN",
        help="Skip URLs matching this glob (or 're:' regex). Repeatable.",
    )
    parser.add_argument(
        "--selector",
        dest="target_selector",
        help="Extract only within this CSS or XPath selector (prefix XPath with 'xpath:' or start with '//')",
    )
    parser.add_argument(
        "--exclude-selector",
        dest="exclude_selectors",
        action="append",
        metavar="SELECTOR",
        help="Strip elements matching this CSS or XPath selector before extraction. Repeatable.",
    )
    parser.add_argument(
        "--schema",
        metavar="JSON",
        default=None,
        help=(
            "JSON map of custom fields to selectors, e.g. "
            '\'{"title": "h1", "price": {"selector": ".price", "attr": "content"}, '
            '"images": {"selector": ".gallery img", "attr": "src", "all": true}}\''
        ),
    )
    parser.add_argument(
        "--schema-file",
        metavar="PATH",
        default=None,
        help="Path to a JSON file containing a schema selector map",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        metavar="CHARS",
        help="Split output into overlapping chunks of this many characters (0 disables chunking)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=_DEFAULT_CHUNK_OVERLAP,
        metavar="CHARS",
        help=f"Overlap between chunks in characters (default: {_DEFAULT_CHUNK_OVERLAP})",
    )
    parser.add_argument(
        "--respect-robots",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Respect robots.txt (default: enabled)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of concurrent worker threads (default: 5)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SECONDS,
        metavar="SECONDS",
        help=f"Delay between requests to the same domain in seconds (default: {REQUEST_DELAY_SECONDS}; 0 for max speed)",
    )
    parser.add_argument(
        "--sitemap",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Discover and crawl URLs directly from sitemap.xml",
    )
    parser.add_argument(
        "--sitemap-url",
        type=str,
        default=None,
        help="Explicit sitemap.xml URL to crawl",
    )
    parser.add_argument(
        "--extract-media",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Extract media links (images, pdf, docs, ppt, video) into media_manifest.json and media_manifest.csv",
    )
    parser.add_argument(
        "--media-mode",
        choices=["both", "media-only"],
        default="both",
        help="Output mode when media extraction is enabled: 'both' (scraped pages + media) or 'media-only' (only media manifest)",
    )
    parser.add_argument(
        "--media-only",
        action="store_true",
        default=False,
        help="Shortcut for --extract-media --media-mode media-only (only save media, skip page text files)",
    )
    parser.add_argument(
        "--download-media",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Download discovered media files locally to <output-dir>/media/<category>/",
    )
    parser.add_argument(
        "--media-types",
        default=None,
        help="Comma-separated media types to extract (choices: image, pdf, doc, ppt, video; default: all)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print extracted content directly to stdout (pipe-friendly)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print extracted JSON directly to stdout",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print target URLs without fetching page bodies",
    )
    # --- Phase 6: local resilience / incremental crawling -------------------
    parser.add_argument(
        "--incremental",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Only re-fetch and re-write pages whose content changed (SHA-256 + "
            "ETag/Last-Modified conditional requests + sitemap lastmod)"
        ),
    )
    parser.add_argument(
        "--resume",
        metavar="JOB_ID",
        default=None,
        help="Resume an interrupted crawl from its local SQLite checkpoint",
    )
    parser.add_argument(
        "--checkpoint",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist queue/visited/failure state locally so crawls can resume (default: enabled)",
    )
    parser.add_argument(
        "--state-db",
        metavar="PATH",
        default=None,
        help="Path to the local crawl-state SQLite DB (default: <output-dir>/.scraper/crawl_state.db)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        metavar="N",
        help="Total attempts per URL before moving it to the dead-letter queue (default: 2)",
    )
    parser.add_argument(
        "--adaptive-rate-limit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Adapt per-domain delays with exponential backoff on 429/5xx responses (default: enabled)",
    )
    parser.add_argument(
        "--dlq",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Track and report dead-letter queue failures (default: disabled)",
    )
    parser.add_argument(
        "--retry-failed",
        metavar="JOB_ID",
        default=None,
        help="Requeue only the failed URLs from a checkpointed job and resume it",
    )
    parser.add_argument(
        "--list-failures",
        metavar="JOB_ID",
        nargs="?",
        const="",
        default=None,
        help="Print the dead-letter queue for a job (or the latest job) and exit",
    )
    parser.add_argument(
        "--worker-id",
        default="",
        help="Worker identifier used for distributed queue claims (default: auto-generated)",
    )
    parser.add_argument(
        "--impersonate",
        choices=["chrome", "safari", "firefox", "none"],
        default=None,
        help="Browser TLS fingerprint to impersonate via curl_cffi",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="Proxy URL (e.g. http://127.0.0.1:8080 or socks5://127.0.0.1:9050)",
    )
    parser.add_argument(
        "--webhook",
        type=str,
        default=None,
        help="POST a crawl summary to this URL when the job completes or fails",
    )
    parser.add_argument(
        "--render-js",
        action="store_true",
        help="Force Playwright rendering for every page (otherwise only used as a fallback)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (.scraperrc or scraper.json)",
    )
    parser.add_argument("--ui", action="store_true", help="Launch the web UI interface")
    parser.add_argument("--port", type=int, default=5000, help="Web UI port (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI host (default: 127.0.0.1)")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = sys.argv[1:] if argv is None else argv
    config_path = None
    for i, a in enumerate(raw_argv):
        if a == "--config" and i + 1 < len(raw_argv):
            config_path = raw_argv[i + 1]
        elif a.startswith("--config="):
            config_path = a.split("=", 1)[1]

    config_defaults = _load_config_file(config_path)
    parser = build_parser()
    if config_defaults:
        valid_keys = {action.dest for action in parser._actions}
        filtered_defaults = {k: v for k, v in config_defaults.items() if k in valid_keys}
        parser.set_defaults(**filtered_defaults)

    args = parser.parse_args(argv)
    if args.ui:
        return args
    if any(getattr(args, name, None) for name in ("resume", "retry_failed")):
        return args
    if getattr(args, "list_failures", None) is not None:
        return args
    if not args.url and not args.sitemap_url and sys.stdin.isatty():
        return _interactive(args)
    return args


def run(args: argparse.Namespace) -> int:
    if getattr(args, "ui", False):
        from .app import run_server

        run_server(host=args.host, port=args.port)
        return 0

    urls, invalid = _parse_urls(args.url or [])
    resume_job_id = getattr(args, "resume", None)
    retry_job_id = getattr(args, "retry_failed", None)
    list_failures_job = getattr(args, "list_failures", None)
    requested_resume = bool(resume_job_id or retry_job_id or list_failures_job is not None)

    # Resolve a checkpointed job before logging/output paths so --resume and
    # --retry-failed can restore the job's original output directory.
    resume_store_path: Path | None = None
    resume_job: dict[str, Any] | None = None
    resume_action = "resume" if resume_job_id else ("retry" if retry_job_id else "list")
    if requested_resume:
        target_job_id = str(resume_job_id or retry_job_id or list_failures_job or "")
        candidates: list[Path] = []
        if getattr(args, "state_db", None):
            candidates.append(Path(args.state_db).expanduser().resolve())
        else:
            candidates.append(default_state_path(args.output_dir))
            candidates.append(default_state_path("./output"))
        for candidate in dict.fromkeys(candidates):
            if not candidate.exists():
                continue
            lookup = CrawlStore(candidate)
            try:
                job = lookup.get_job(target_job_id) if target_job_id else (
                    (lookup.list_jobs(limit=1) or [None])[0]
                )
            finally:
                lookup.close()
            if job is not None:
                resume_store_path = candidate
                resume_job = job
                break
        if resume_job is None:
            sys.stderr.write(
                f"Could not find checkpointed job '{target_job_id or '(latest)'}'. "
                f"Looked in: {', '.join(str(c) for c in dict.fromkeys(candidates))}\n"
            )
            return 2

        cfg = dict(resume_job.get("config") or {})
        job_output = str(resume_job.get("output_dir") or cfg.get("output_dir") or "")
        if job_output:
            args.output_dir = job_output
        if not getattr(args, "state_db", None):
            args.state_db = str(resume_store_path)
        if not urls:
            urls = list(cfg.get("urls") or [])
        for key, value in cfg.items():
            if key == "urls":
                continue
            if value is not None and hasattr(args, key):
                setattr(args, key, value)
        if resume_action == "retry":
            retry_store = CrawlStore(resume_store_path)
            try:
                requeued = retry_store.requeue_failed(str(resume_job["job_id"]))
            finally:
                retry_store.close()
            if requeued == 0:
                sys.stderr.write(f"Job '{resume_job['job_id']}' has no failed URLs to retry.\n")
                return 2
            resume_job_id = str(resume_job["job_id"])
            sys.stderr.write(f"Requeued {requeued} failed URL(s) for job {resume_job_id}.\n")

    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "scrape_log.txt"

    is_piped = getattr(args, "stdout", False) or getattr(args, "json", False)
    if is_piped:
        handlers = [logging.StreamHandler(sys.stderr)]
    else:
        handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stderr)]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    logger = logging.getLogger("website_scraper")

    if resume_action == "list" and requested_resume:
        state_path = resume_store_path or default_state_path(output)
        lookup = CrawlStore(state_path)
        try:
            failures = lookup.failures(str(resume_job["job_id"])) if resume_job else []
            job_id_out = str(resume_job["job_id"]) if resume_job else ""
        finally:
            lookup.close()
        if getattr(args, "json", False):
            print(json.dumps({"job_id": job_id_out, "failures": failures}, indent=2))
        else:
            print(f"Dead-letter queue for job {job_id_out or '(none)'}: {len(failures)} URL(s)")
            for failure in failures:
                print(
                    f"  - [{failure.get('error_category')}] {failure.get('url')} "
                    f"(attempts={failure.get('attempts')}): {failure.get('message')}"
                )
        logging.shutdown()
        return 0

    for value in invalid:
        logger.warning("Invalid URL skipped: %s", value)
    if not urls and not getattr(args, "sitemap_url", None):
        logger.error("No valid URLs supplied. Pass --url or run interactively.")
        return 2
    if args.max_pages < 1:
        logger.error("--max-pages must be at least 1.")
        return 2
    if args.depth < 0 or args.depth > MAX_DEPTH:
        logger.error("--depth must be between 0 and %s.", MAX_DEPTH)
        return 2
    args.format = str(getattr(args, "format", "txt") or "txt").lower().strip()
    if args.format not in OUTPUT_FORMATS:
        logger.error("--format must be one of: %s.", ", ".join(OUTPUT_FORMATS))
        return 2
    if args.chunk_size < 0:
        logger.error("--chunk-size cannot be negative.")
        return 2
    if args.chunk_overlap < 0:
        logger.error("--chunk-overlap cannot be negative.")
        return 2

    include_patterns = parse_patterns(args.include_pattern or [])
    exclude_patterns = parse_patterns(args.exclude_pattern or [])
    exclude_selectors = parse_selectors(args.exclude_selectors or [])
    try:
        validate_selectors(args.target_selector, exclude_selectors)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    try:
        schema_spec = _load_schema(getattr(args, "schema", None), getattr(args, "schema_file", None))
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    if schema_spec:
        logger.info("Schema fields: %s", ", ".join(schema_spec))

    impersonate_val = args.impersonate
    if impersonate_val == "none":
        impersonate_val = None
    try:
        webhook_url = validate_webhook_url(getattr(args, "webhook", None))
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    if getattr(args, "dry_run", False):
        crawler = Crawler(
            args.depth,
            args.max_pages,
            args.same_domain,
            logger,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            respect_robots=args.respect_robots,
            concurrency=args.concurrency,
            delay=getattr(args, "delay", REQUEST_DELAY_SECONDS),
            sitemap=args.sitemap,
            sitemap_url=args.sitemap_url,
            impersonate=impersonate_val,
            proxy=args.proxy,
            render_js=getattr(args, "render_js", False),
        )
        valid_targets = []
        crawled_any = False
        try:
            for page in crawler.crawl(urls):
                crawled_any = True
                valid_targets.append(page.url)
                if not getattr(args, "json", False):
                    logger.info("[depth %d] Discovered %s", page.depth, page.url)
        except Exception as exc:
            logger.warning("Crawl discovery error: %s", exc)

        if not crawled_any:
            discovered_urls = list(urls)
            if args.sitemap or args.sitemap_url:
                if args.sitemap_url:
                    discovered_urls.extend(fetch_sitemap_urls(args.sitemap_url, max_urls=args.max_pages))
                elif args.sitemap:
                    for seed in urls:
                        for s_url in discover_sitemap_urls(seed):
                            discovered_urls.extend(fetch_sitemap_urls(s_url, max_urls=args.max_pages))

            for u in dict.fromkeys(discovered_urls):
                if not crawler.url_filter.excluded_by(u):
                    valid_targets.append(u)
                    if len(valid_targets) >= args.max_pages:
                        break

        if getattr(args, "json", False):
            print(json.dumps({"dry_run": True, "target_urls": valid_targets, "total": len(valid_targets)}, indent=2))
        else:
            print(f"Dry run: {len(valid_targets)} target URL(s) to crawl:")
            for u in valid_targets:
                print(f"  - {u}")
        return 0

    started = time.monotonic()
    started_iso = datetime.now(timezone.utc).isoformat()
    checkpoint_enabled = bool(getattr(args, "checkpoint", True)) or bool(resume_job_id)
    incremental_enabled = bool(getattr(args, "incremental", False))
    state_path = (
        Path(args.state_db).expanduser().resolve()
        if getattr(args, "state_db", None)
        else default_state_path(output)
    )
    job_id = resume_job_id or uuid.uuid4().hex[:12]
    store: CrawlStore | None = None
    delta: DeltaCache | None = None
    if checkpoint_enabled or incremental_enabled or resume_job_id:
        try:
            store = CrawlStore(state_path)
            if resume_job_id:
                store.update_job(job_id, status="running")
            else:
                store.create_job(
                    job_id,
                    output_dir=str(output),
                    config={
                        "urls": urls,
                        "depth": args.depth,
                        "max_pages": args.max_pages,
                        "same_domain": args.same_domain,
                        "output_dir": str(output),
                        "output_format": args.format,
                        "include_patterns": include_patterns,
                        "exclude_patterns": exclude_patterns,
                        "target_selector": args.target_selector,
                        "exclude_selectors": exclude_selectors,
                        "schema": schema_spec,
                        "chunk_size": args.chunk_size,
                        "chunk_overlap": args.chunk_overlap,
                        "respect_robots": args.respect_robots,
                        "concurrency": args.concurrency,
                        "delay": getattr(args, "delay", REQUEST_DELAY_SECONDS),
                        "sitemap": args.sitemap,
                        "sitemap_url": args.sitemap_url,
                        "impersonate": impersonate_val,
                        "proxy": args.proxy,
                        "render_js": getattr(args, "render_js", False),
                        "incremental": incremental_enabled,
                        "max_retries": getattr(args, "max_retries", 2),
                        "adaptive_rate_limit": getattr(args, "adaptive_rate_limit", True),
                        "output_format": args.format,
                    },
                    status="running",
                )
            if incremental_enabled:
                delta = DeltaCache(state_path)
            logger.info("Checkpointing enabled: job %s (%s)", job_id, state_path)
            if incremental_enabled:
                logger.info("Incremental mode enabled: SHA-256 + ETag/Last-Modified delta detection")
            if resume_job_id:
                logger.info("Resuming crawl job %s", job_id)
        except Exception as exc:
            logger.warning("Could not initialize crawl checkpoint: %s", exc)
            store = None
            delta = None
            checkpoint_enabled = False

    media_only_flag = bool(getattr(args, "media_only", False))
    download_media_flag = bool(getattr(args, "download_media", False))
    extract_media_flag = bool(getattr(args, "extract_media", False)) or media_only_flag or download_media_flag
    media_mode = "media-only" if media_only_flag else getattr(args, "media_mode", "both")
    media_only = (media_mode == "media-only")
    media_types_set = parse_media_types(getattr(args, "media_types", None))

    writer = OutputWriter(
        args.output_dir,
        args.format,
        media_only=media_only,
        incremental=incremental_enabled,
    )
    media_collector = None
    if extract_media_flag:
        media_collector = MediaCollector(
            allowed_types=media_types_set,
            download=download_media_flag,
            session=None,
            logger=logger,
        )
    crawler = Crawler(
        args.depth,
        args.max_pages,
        args.same_domain,
        logger,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        respect_robots=args.respect_robots,
        concurrency=args.concurrency,
        delay=getattr(args, "delay", REQUEST_DELAY_SECONDS),
        sitemap=args.sitemap,
        sitemap_url=args.sitemap_url,
        impersonate=impersonate_val,
        proxy=args.proxy,
        render_js=getattr(args, "render_js", False),
        store=store,
        delta=delta,
        job_id=job_id if store is not None else None,
        resume=bool(resume_job_id),
        worker_id=getattr(args, "worker_id", "") or "",
        max_retries=max(1, int(getattr(args, "max_retries", 2) or 2)),
        adaptive_delay=bool(getattr(args, "adaptive_rate_limit", True)),
    )
    crawled = saved = failed = 0
    changed = unchanged = 0
    collected_documents = []
    collected_depths: list[int] = []
    saved_pages_meta: list[dict[str, Any]] = []
    try:
        if media_collector is not None:
            media_collector.session = crawler.fetcher.session

        for page in crawler.crawl(urls):
            crawled += 1
            if getattr(page, "unchanged", False):
                unchanged += 1
                logger.info("[depth %d] Unchanged (skipped) %s", page.depth, page.url)
                continue
            changed += 1
            try:
                document = extract_structured(
                    page.html,
                    url=page.url,
                    target_selector=args.target_selector,
                    exclude_selectors=exclude_selectors,
                    schema=schema_spec,
                    chunk_size=args.chunk_size,
                    chunk_overlap=args.chunk_overlap,
                    extract_media=extract_media_flag,
                    media_types=media_types_set,
                )
            except Exception as exc:
                failed += 1
                logger.warning("Extraction failed for %s: %s", page.url, exc)
                continue

            if media_collector is not None:
                if getattr(document, "media", None) is not None:
                    from .media import MediaItem
                    doc_items = [
                        MediaItem(
                            page_url=m.get("page_url", page.url),
                            media_type=m.get("media_type", "image"),
                            media_url=m.get("media_url") or m.get("url", ""),
                            filename=m.get("filename", ""),
                            extension=m.get("extension", ""),
                            alt=m.get("alt", ""),
                            downloaded_path=m.get("downloaded_path", ""),
                            download_status=m.get("download_status", "pending"),
                            size_bytes=m.get("size_bytes", 0),
                        )
                        for m in document.media
                        if isinstance(m, dict) and (m.get("media_url") or m.get("url"))
                    ]
                    new_media = media_collector.add_items(
                        doc_items,
                        output_dir=output if download_media_flag else None,
                    )
                else:
                    new_media = media_collector.add_page_media(
                        page.url,
                        page.html,
                        output_dir=output if download_media_flag else None,
                    )
                if not is_piped and new_media:
                    print(f"  [media] extracted {len(new_media)} media file(s) from {page.url}")

            if is_piped:
                collected_documents.append(document)
                collected_depths.append(page.depth)
                if getattr(args, "stdout", False) and args.format == "jsonl":
                    print(json.dumps(document.to_dict()))
                elif not getattr(args, "json", False) and not (
                    getattr(args, "stdout", False)
                    and args.format in {"json", "jsonl", "csv", "sqlite"}
                ):
                    content = document.markdown if args.format == "md" else document.text
                    if saved > 0:
                        print("\n---\n")
                    print(content)

            if not media_only:
                filename = writer.save_document(document, page.depth)
                if hasattr(crawler, "record_page_saved"):
                    crawler.record_page_saved(page, filename)
                saved += 1
                try:
                    size_bytes = (output / filename).stat().st_size if filename else 0
                except OSError:
                    size_bytes = 0
                saved_pages_meta.append({
                    "url": document.url,
                    "title": document.title,
                    "file": filename,
                    "depth": page.depth,
                    "bytes": size_bytes,
                    "format": args.format,
                })
                if not is_piped:
                    print(f"[depth {page.depth}] saving {page.url} -> {output / filename}")
                else:
                    sys.stderr.write(f"[depth {page.depth}] saved {page.url}\n")
            else:
                writer.save_document(document, page.depth)
                if not is_piped:
                    print(f"[depth {page.depth}] scanned {page.url} (media-only mode)")
    finally:
        writer.finalize()
        if media_collector is not None:
            json_m, csv_m = media_collector.write_manifests(output)
            if not is_piped:
                print(f"  [media] saved manifests -> {json_m.name}, {csv_m.name}")

    if getattr(args, "json", False) or (getattr(args, "stdout", False) and args.format == "json"):
        if len(collected_documents) == 1:
            print(json.dumps(collected_documents[0].to_dict(), indent=2))
        else:
            print(json.dumps([d.to_dict() for d in collected_documents], indent=2))

    if getattr(args, "stdout", False) and args.format == "csv":
        import csv as _csv

        stdout_writer = _csv.DictWriter(sys.stdout, fieldnames=_ROW_FIELDS)
        stdout_writer.writeheader()
        for document, page_depth in zip(collected_documents, collected_depths):
            stdout_writer.writerow(_document_row(document, page_depth, datetime.now(timezone.utc).isoformat()))
    elif getattr(args, "stdout", False) and args.format == "sqlite":
        sys.stderr.write("Note: sqlite output is saved in the output directory; nothing is printed to stdout.\n")

    elapsed = time.monotonic() - started
    skipped = len(crawler.skipped_reasons) + len(invalid)
    files_written = len(writer.written_files) + 1
    media_stats = media_collector.get_summary() if media_collector else None
    media_info_str = ""
    if media_stats:
        media_info_str = f", media found={media_stats['total_media']}, media downloaded={media_stats['downloaded']}"
    summary_msg = (
        f"\nSummary: pages crawled={crawled}, pages saved={saved}, pages changed={changed}, "
        f"pages unchanged={unchanged}, pages failed={failed}, "
        f"pages skipped={skipped}, files written={files_written}, format={args.format}{media_info_str}, elapsed={elapsed:.2f}s"
    )
    if job_id and store is not None:
        summary_msg += f"\nJob id: {job_id} (state: {state_path})"
        summary_msg += "\nResume with: --resume " + job_id
    if is_piped:
        sys.stderr.write(summary_msg + "\n")
    else:
        print(summary_msg)

    if store is not None:
        try:
            failures = store.failures(job_id)
            queue_snapshot = store.queue_stats(job_id)
            store.update_job(
                job_id,
                status="completed",
                stats={
                    "pages_crawled": crawled,
                    "pages_saved": saved,
                    "pages_changed": changed,
                    "pages_unchanged": unchanged,
                    "pages_failed": failed,
                    "queue": queue_snapshot,
                    "failures": len(failures),
                },
            )
            if failures and getattr(args, "dlq", False):
                logger.warning(
                    "Dead-letter queue: %d URL(s). Retry with: --retry-failed %s",
                    len(failures), job_id,
                )
        except Exception as exc:  # pragma: no cover
            logger.debug("Could not finalize checkpoint: %s", exc)
        finally:
            store.close()
    if delta is not None:
        delta.close()

    if webhook_url:
        notify(
            webhook_url,
            event="crawl.completed",
            status="completed",
            urls=urls,
            stats={
                "pages_crawled": crawled,
                "pages_saved": saved,
                "pages_failed": failed,
                "pages_skipped": skipped,
                "files_written": files_written,
                "elapsed_seconds": round(elapsed, 3),
            },
            output_dir=str(output),
            started_at=started_iso,
            finished_at=datetime.now(timezone.utc).isoformat(),
            pages=saved_pages_meta,
            logger=logger,
        )
    logging.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
