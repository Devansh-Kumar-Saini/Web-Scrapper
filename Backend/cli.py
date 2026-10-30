"""Command-line interface for the website scraper."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .config import DEFAULT_MAX_PAGES, MAX_DEPTH
    from .crawler import Crawler
    from .extractor import _DEFAULT_CHUNK_OVERLAP, extract_structured, validate_selectors
    from .filters import parse_patterns, parse_selectors
    from .sitemap import discover_sitemap_urls, fetch_sitemap_urls
    from .writer import OUTPUT_FORMATS, OutputWriter
except ImportError:  # pragma: no cover - direct script execution
    from config import DEFAULT_MAX_PAGES, MAX_DEPTH
    from crawler import Crawler
    from extractor import _DEFAULT_CHUNK_OVERLAP, extract_structured, validate_selectors
    from filters import parse_patterns, parse_selectors
    from sitemap import discover_sitemap_urls, fetch_sitemap_urls
    from writer import OUTPUT_FORMATS, OutputWriter


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
        description="Crawl websites and save clean text, Markdown, JSON, or JSONL locally."
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
        help="Output format: txt (default), md, json, or jsonl",
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
    parser.add_argument("--selector", dest="target_selector", help="Extract only within this CSS selector")
    parser.add_argument(
        "--exclude-selector",
        dest="exclude_selectors",
        action="append",
        metavar="SELECTOR",
        help="Strip elements matching this CSS selector before extraction. Repeatable.",
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
    if not args.url and not args.sitemap_url and sys.stdin.isatty():
        return _interactive(args)
    return args


def run(args: argparse.Namespace) -> int:
    if getattr(args, "ui", False):
        from .app import run_server

        run_server(host=args.host, port=args.port)
        return 0

    urls, invalid = _parse_urls(args.url or [])
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

    impersonate_val = args.impersonate
    if impersonate_val == "none":
        impersonate_val = None

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
            sitemap=args.sitemap,
            sitemap_url=args.sitemap_url,
            impersonate=impersonate_val,
            proxy=args.proxy,
        )
        discovered_urls = list(urls)
        if args.sitemap or args.sitemap_url:
            if args.sitemap_url:
                discovered_urls.extend(fetch_sitemap_urls(args.sitemap_url, max_urls=args.max_pages))
            elif args.sitemap:
                for seed in urls:
                    for s_url in discover_sitemap_urls(seed):
                        discovered_urls.extend(fetch_sitemap_urls(s_url, max_urls=args.max_pages))

        valid_targets = []
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
    writer = OutputWriter(args.output_dir, args.format)
    crawler = Crawler(
        args.depth,
        args.max_pages,
        args.same_domain,
        logger,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        respect_robots=args.respect_robots,
        concurrency=args.concurrency,
        sitemap=args.sitemap,
        sitemap_url=args.sitemap_url,
        impersonate=impersonate_val,
        proxy=args.proxy,
    )
    crawled = saved = failed = 0
    collected_documents = []
    try:
        for page in crawler.crawl(urls):
            crawled += 1
            try:
                document = extract_structured(
                    page.html,
                    url=page.url,
                    target_selector=args.target_selector,
                    exclude_selectors=exclude_selectors,
                    chunk_size=args.chunk_size,
                    chunk_overlap=args.chunk_overlap,
                )
            except Exception as exc:
                failed += 1
                logger.warning("Extraction failed for %s: %s", page.url, exc)
                continue

            if is_piped:
                collected_documents.append(document)
                if getattr(args, "stdout", False) and args.format == "jsonl":
                    print(json.dumps(document.to_dict()))
                elif not getattr(args, "json", False) and not (getattr(args, "stdout", False) and args.format in {"json", "jsonl"}):
                    content = document.markdown if args.format == "md" else document.text
                    if saved > 0:
                        print("\n---\n")
                    print(content)

            filename = writer.save_document(document, page.depth)
            saved += 1
            if not is_piped:
                print(f"[depth {page.depth}] saving {page.url} -> {output / filename}")
            else:
                sys.stderr.write(f"[depth {page.depth}] saved {page.url}\n")
    finally:
        writer.finalize()
        logging.shutdown()

    if getattr(args, "json", False) or (getattr(args, "stdout", False) and args.format == "json"):
        if len(collected_documents) == 1:
            print(json.dumps(collected_documents[0].to_dict(), indent=2))
        else:
            print(json.dumps([d.to_dict() for d in collected_documents], indent=2))

    elapsed = time.monotonic() - started
    skipped = len(crawler.skipped_reasons) + len(invalid)
    files_written = len(writer.written_files) + 1
    summary_msg = (
        f"\nSummary: pages crawled={crawled}, pages saved={saved}, pages failed={failed}, "
        f"pages skipped={skipped}, files written={files_written}, format={args.format}, elapsed={elapsed:.2f}s"
    )
    if is_piped:
        sys.stderr.write(summary_msg + "\n")
    else:
        print(summary_msg)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
