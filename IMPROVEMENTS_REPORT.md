# Website Scraper — Improvement Checklist

Status snapshot of the original roadmap. Completed items are checked.

## Done

### Extraction & output
- [x] Markdown (`.md`) export with headings, lists, links, tables, images, and code blocks.
- [x] Structured JSON and JSONL output with title, description, author, publish date, canonical URL, links, images, headings, and word count.
- [x] Character-based chunking with configurable size and overlap for RAG pipelines.
- [x] CSS selector targeting (`--selector`) and excluded selectors (`--exclude-selector`).
- [x] XPath selector targeting and exclusions (`xpath:` prefix or `//`-style expressions).
- [x] Structured schema extraction via a selector map with text, attribute, and multi-match fields.
- [x] Strip chrome (ads, sidebars, cookie banners) before extraction.
- [x] TXT, MD, JSON, JSONL, CSV, and SQLite writers plus `index.json` and `scrape_log.txt`.

### Crawling engine
- [x] Concurrent worker pool with configurable concurrency.
- [x] Per-domain politeness delay.
- [x] `robots.txt` enforcement.
- [x] `sitemap.xml` auto-detection and parsing (including sitemap indexes).
- [x] URL include/exclude filters with glob and `re:` regex syntax.
- [x] Same-domain restriction and configurable depth/page caps.
- [x] Browser headers, User-Agent rotation, and `curl_cffi` TLS impersonation.
- [x] HTTP/SOCKS proxy support.
- [x] Lazy-loaded, reusable Playwright browser with page reuse, timeouts, and asset blocking.

### Interfaces
- [x] Instant single-page API (`GET`/`POST /api/scrape`) returning Markdown, text, HTML, or JSON.
- [x] Background crawl API with start/stop/status endpoints.
- [x] Live progress over Server-Sent Events (SSE).
- [x] CLI support for `--stdout`, `--json`, `--dry-run`, `--config`, and `--webhook`.
- [x] Web UI with advanced extraction panel, single-URL inspector, CSS/XPath selector preview, schema fields, and live logs.
- [x] ZIP download in original or converted formats (MD, TXT, JSON, JSONL, CSV, SQLite).
- [x] Webhook completion callbacks.
- [x] Importable Python library (`Crawler`, `scrape_url`).

### Packaging, tests & release
- [x] MIT `LICENSE`.
- [x] `pyproject.toml` with PEP 621 metadata, console script, and ruff/mypy config.
- [x] `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `/api/health` check.
- [x] Multi-architecture Docker image (`linux/amd64`, `linux/arm64`) on GHCR.
- [x] Automated Docker publishing via GitHub Actions.
- [x] Headless-only Chromium image (~1.43 GB on disk, ~384 MB download).
- [x] Comprehensive README with screenshots, CLI/API/library docs, and Docker guide.
- [x] Test suite for phases 1–3 plus output-directory handling (99 tests).

