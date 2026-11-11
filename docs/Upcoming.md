# Website Scraper — Roadmap & Improvement Report

Status snapshot of completed milestones alongside the forward-looking roadmap for next-generation web scraping, browser automation, crawling resilience, and developer tooling.

---

## Completed Roadmap (Phases 1–4)

All core milestones from the original architecture and feature specification are fully implemented and verified.

### Extraction & Output
- [x] Markdown (`.md`) export with headings, lists, links, tables, images, and code blocks.
- [x] Structured JSON and JSONL output with title, description, author, publish date, canonical URL, links, images, headings, and word count.
- [x] Character-based chunking with configurable size and overlap.
- [x] CSS selector targeting (`--selector`) and excluded selectors (`--exclude-selector`).
- [x] XPath selector targeting and exclusions (`xpath:` prefix or `//`-style expressions).
- [x] Structured schema extraction via a selector map with text, attribute, and multi-match fields.
- [x] Strip chrome (ads, sidebars, cookie banners) before extraction.
- [x] TXT, MD, JSON, JSONL, CSV, and SQLite writers plus `index.json` and `scrape_log.txt`.

### Crawling Engine
- [x] Concurrent worker pool with configurable concurrency.
- [x] Per-domain politeness delay.
- [x] `robots.txt` enforcement.
- [x] `sitemap.xml` auto-detection and parsing (including sitemap indexes).
- [x] URL include/exclude filters with glob and `re:` regex syntax.
- [x] Same-domain restriction and configurable depth/page caps.
- [x] Browser headers, User-Agent rotation, and `curl_cffi` TLS impersonation.
- [x] HTTP/SOCKS proxy support.
- [x] Lazy-loaded, reusable Playwright browser with page reuse, timeouts, and asset blocking.

### Interfaces & Developer Tooling
- [x] Instant single-page API (`GET`/`POST /api/scrape`) returning Markdown, text, HTML, or JSON.
- [x] Background crawl API with start/stop/status endpoints.
- [x] Live progress over Server-Sent Events (SSE).
- [x] CLI support for `--stdout`, `--json`, `--dry-run`, `--config`, and `--webhook`.
- [x] Web UI with advanced extraction panel, single-URL inspector, CSS/XPath selector preview, schema fields, and live logs.
- [x] ZIP download in original or converted formats (MD, TXT, JSON, JSONL, CSV, SQLite).
- [x] Webhook completion callbacks with delivery retry.
- [x] Importable Python library (`Crawler`, `scrape_url`).

### Packaging, Tests & Release
- [x] MIT `LICENSE`.
- [x] `pyproject.toml` with PEP 621 metadata, console script, and ruff/mypy config.
- [x] `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `/api/health` check.
- [x] Multi-architecture Docker image (`linux/amd64`, `linux/arm64`) on GHCR.
- [x] Automated Docker publishing via GitHub Actions.
- [x] Headless-only Chromium image (~1.43 GB on disk, ~384 MB download).
- [x] Comprehensive README with screenshots, CLI/API/library docs, and Docker guide.
- [x] Test suite for phases 1–3 plus output-directory handling (99 tests).

---

## Future Roadmap & Planned Features (Phases 5–8)

This future plan focuses strictly on **core web scraping excellence, browser automation, performance, enterprise scalability, and developer experience** (non-AI).

```
+-----------------------------------------------------------------------------------------+
|                              Website Scraper Future Roadmap                             |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [ Phase 5: Browser Automation & Stealth   ] --> Actions, Auth, PDF/Screenshots, Sniff  |
|  [ Phase 6: Scale, Resilience & Queuing    ] --> Delta crawls, Redis queue, DLQ, Resume |
|  [ Phase 7: Extraction Pipelines & Data    ] --> Readability, Tables, Parquet, Assets   |
|  [ Phase 8: Scheduling & Cloud Exports     ] --> Cron, Change alerts, S3/Postgres       |
|  [ Phase 9: UI Innovations & Observability ] --> Visual selector, Crawl graph, OpenAPI  |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

### Phase 5: Dynamic Browser Automation, Stealth & Network Sniffing
*Objective: Master complex Single-Page Apps (SPAs), authenticated portals, and bypass anti-bot defenses.*

- [ ] **Declarative Pre-Scrape Browser Actions**
  - Configurable interaction recipes executed before DOM extraction:
    - `click`: Expand "Read more" buttons, accordions, dropdowns, and tab panels.
    - `scroll`: Auto-scroll / infinite scroll to trigger lazy loading of catalogs or feeds.
    - `wait_for`: Wait for dynamic DOM selectors or network-idle states before extracting.
    - `type` / `press`: Fill search inputs or trigger keyboard events.
  - Action steps configurable via CLI (`--action "click:.load-more" --action "scroll:5"`) or JSON/YAML config.

- [ ] **Session State & Authenticated Crawling**
  - Cookie and storage state import/export (`storageState.json`).
  - Scrape behind logins, internal company portals, and staging environments.
  - Automated login runner: fill username/password forms, submit, and persist auth cookies for the crawl session.

- [ ] **Network Request Interception & API Sniffing**
  - Intercept background XHR/Fetch API calls in modern SPAs (React, Next.js, Vue).
  - Capture raw JSON payloads directly from backend API endpoints before DOM rendering (faster and cleaner than parsing HTML).

- [ ] **Stealth & Bot Mitigation Hardening**
  - `playwright-stealth` integration: mask `navigator.webdriver`, canvas fingerprints, and WebGL signatures.
  - Advanced proxy pool management: automatic proxy rotation with health checks, failover, and latency benchmarking.
  - Challenge detection: identify Cloudflare, PerimeterX, and CAPTCHA block pages with clear error reporting.

- [ ] **Visual Media & Document Capture**
  - High-DPI full-page and element-specific screenshot capture (`.png`, `.webp`).
  - Clean printable PDF generation with optional print stylesheet emulation (stripping headers, footers, and ads).

---

### Phase 6: Scalability, Queuing & Crawl Resilience
*Objective: Scale to 100,000+ page datasets with rock-solid fault tolerance and state resumption.*

- [ ] **Incremental / Delta Crawling (Smart Change Detection)**
  - Content hashing (SHA-256) and HTTP cache validation (`ETag`, `Last-Modified`).
  - Respect sitemap `lastmod` timestamps to skip unchanged pages.
  - Delta updates: only re-fetch, extract, and write pages that have genuinely changed since the last crawl.

- [ ] **Persistent & Distributed Queue (Redis / Celery)**
  - Optional Redis-backed URL queue allowing multiple crawler instances/containers to scrape concurrently across machines.
  - Distributed worker coordination without duplicate URL processing.

- [ ] **Crawl State Checkpointing & Resume**
  - Checkpoint URL queue, visited set, and progress to SQLite/Redis.
  - Resume interrupted crawls (`--resume <job-id>`) seamlessly after network drops or container restarts.

- [ ] **Dead-Letter Queue (DLQ) & Intelligent Retry**
  - Dedicated failure queue categorizing errors (DNS resolution, HTTP 403, HTTP 429, Playwright timeouts).
  - UI and CLI retry button to re-run only failed URLs without restarting the entire crawl.
  - Adaptive rate limiting with exponential backoff and circuit-breaking per domain.

---

### Phase 7: Advanced Data Extraction & Export Pipelines
*Objective: Expand extraction capabilities to tables, downloadable assets, and tabular data formats.*

- [ ] **Algorithmic Main Content Extraction (Readability / Trafilatura Engine)**
  - Pure heuristic/density-based content detection (Mozilla Readability & Trafilatura algorithms).
  - Automatically isolates main articles/content on blogs and news sites without manual CSS/XPath selectors.
  - Robust against obfuscated or dynamic CSS class names (Tailwind, CSS modules).

- [ ] **Structured HTML Table Parser**
  - Detect and parse complex HTML `<table>` elements into structured JSON, CSV, or Excel (`.xlsx`) datasets.
  - Handles nested headers (`colspan`, `rowspan`) and malformed tables cleanly.

- [x] **Media Extractor & Asset Downloader**
  - Extract and catalog all media links (Images, PDFs, Docs, PPTs, Videos) into `media_manifest.json` and `media_manifest.csv` with source page URL, media type, and media URL.
  - Configurable modes: combine with standard web scraping or run in media-only mode (skips regular page text/markdown files).
  - Optional local downloading of binary media assets organized by category in `<output>/media/<category>/`.
  - Full CLI (`--extract-media`, `--media-mode`, `--media-only`, `--download-media`, `--media-types`), REST API, and Web UI integration.

- [ ] **Data Validation & Schema Assertions**
  - Validate extracted schema fields against JSON Schema or validation rules (e.g., regex patterns, required fields, numeric ranges).
  - Highlight extraction anomalies or schema mismatches in crawl logs and summary reports.

- [ ] **Columnar & Database Exporters**
  - Apache Parquet (`.parquet`) export for high-performance big data analytics.
  - Excel (`.xlsx`) export with formatted headers and auto-sized columns.

---

### Phase 8: Automation, Scheduling & Cloud Storage Sync
*Objective: Automate recurring scraping jobs and integrate with enterprise storage systems.*

- [ ] **Built-in Cron & Recurring Job Scheduler**
  - Schedule recurring background crawls using cron syntax (e.g. `0 2 * * *` for nightly runs) or interval timers directly in the Web UI / CLI daemon.
  - Run schedules as lightweight headless background services.

- [ ] **Change-Detection Monitoring & Alerts**
  - Diff extracted page text or schema values against historical versions.
  - Send alerts (webhooks, email, Slack, Discord) when monitored pages change (e.g., price updates, out-of-stock changes, terms of service revisions).

- [ ] **Cloud Storage & Database Sync**
  - Direct upload of scrape results to AWS S3, Google Cloud Storage, or Cloudflare R2.
  - Direct table upsert into PostgreSQL, MySQL, or DuckDB.

---

### Phase 9: UI Innovations, Observability & Developer Tools
*Objective: Provide visual point-and-click tooling, live network graphs, and production monitoring.*

- [ ] **Visual Point-and-Click Selector Builder (Web UI)**
  - Embedded sandboxed browser preview within the Web UI.
  - Clicking any element on the page highlights it and automatically generates the most concise CSS selector, XPath, or schema mapping.

- [ ] **Real-Time Crawl Topology Graph**
  - Interactive node-link visualization (D3.js / Cytoscape) displaying URL hierarchies, link depth, and crawl status in real time.

- [ ] **OpenAPI / Swagger Interactive Documentation**
  - Auto-generated interactive OpenAPI v3 specification and Swagger UI hosted at `/docs`.
  - Try-it-out API console for all scraper endpoints.

- [ ] **Prometheus Metrics Endpoint (`/metrics`)**
  - Expose operational metrics:
    - Scrape speed (pages/second, bytes/second).
    - HTTP response code distribution (2xx, 3xx, 4xx, 5xx).
    - Per-domain latency histograms.
    - Worker pool utilization and active Playwright browser instances.

---

## Prioritized Implementation Milestones

| Priority | Feature Pillar | Target Milestones | Primary Benefit |
|---|---|---|---|
| **P0 (Next)** | **Browser Automation & Actions** | Pre-scrape actions (click/scroll), `storageState` auth, API sniffing | Complete access to modern SPAs & protected sites |
| **P1** | **Scale & Resilience** | Incremental / delta crawling, Resume/Checkpointing, DLQ retry queue | Bandwidth savings & zero-loss long crawls |
| **P2** | **Data Pipelines & Tables** | Readability fallback, Table-to-CSV/Excel, Asset/PDF downloader | Versatile structured extraction beyond plain text |
| **P3** | **Scheduling & UI** | Cron scheduler, Visual selector builder, OpenAPI docs, Prometheus | Enterprise automation & streamlined dev experience |
