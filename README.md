# Website Content Scraper

A free, self-hosted, developer-first web scraper and crawler. It follows links to a configurable depth and saves clean **text, Markdown, JSON, or JSONL** locally — no accounts, no hosted scraping APIs, no per-request fees. It features a modern, responsive web UI dashboard with live telemetry and a full REST/SSE API.

Typical uses: feeding documentation into an LLM/RAG pipeline, collecting a dataset, archiving a site, or testing selectors and URL filters against a real page.

![Home Page Image](docs/screenshots/homePage.png)
![Scrapping Image](docs/screenshots/scrapping.png)

## Features

- **Modern Web UI Dashboard**: Single-page application interface for configuring crawls, inspecting pages live, and browsing output files.
- **RAG-ready Markdown** with headings, lists, links, tables, images, and code blocks preserved.
- **Structured JSON / JSONL** with title, description, author, publish date, canonical URL, links, images, headings, and optional chunks.
- **CSV and SQLite output** (`pages.csv`, `pages.db`) for spreadsheets, pandas, and SQL analysis.
- **Instant single-page scrape API** (`POST /api/scrape`) for `curl` and application code.
- **URL filtering** with shell globs or regular expressions (`include` / `exclude`).
- **Targeted extraction** using CSS or XPath selectors, plus selectors to strip ads, sidebars, and cookie banners.
- **Custom schema extraction** via a JSON selector map (e.g. product title, price, images) saved with every page.
- **Polite crawling**: per-domain pacing and `robots.txt` enforcement.
- **Scale & Resilience (100% Local)**:
  - **Incremental / Delta Crawling**: Smart change detection using SHA-256 content hashing, `ETag`/`Last-Modified` conditional requests, and sitemap `lastmod` timestamps to skip unchanged pages.
  - **Durable Checkpointing & Resumption**: All crawl queue state, visited records, and progress are persisted locally in SQLite (`<output>/.scraper/crawl_state.db`) with zero external databases or API keys.
  - **Dead-Letter Queue (DLQ) & Intelligent Retries**: Categorized failure queue with exponential backoff, per-domain circuit breakers, and 1-click retry for failed URLs.
- **Media Extractor & Downloader**: Discovers and catalogs all images, PDFs, docs, presentations, and videos into `media_manifest.json` and `media_manifest.csv`, with optional local asset downloading.
- **JavaScript rendering** via a lazily loaded, reusable local Playwright browser (optional).
- **Live progress** in the web UI over Server-Sent Events (SSE).

## Quick Start

### 1. Local Python Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: enable JavaScript rendering for React/Vue/Next.js pages
playwright install chromium
```

Start the Web UI server:

```bash
python main.py
```

Then open **`http://localhost:5000`** in your browser.

You can customize the host and port:

```bash
python main.py --port 8080 --host 127.0.0.1
```

Or install the package locally:

```bash
pip install -e .
website-scraper
```

### 2. Run with Docker

No Python setup needed. The image bundles Python, all dependencies, and Chromium
for JavaScript rendering.

```bash
# Build and run
docker build -t website-scraper .
docker run -d --name website-scraper \
  -p 5000:5000 \
  -v "$(pwd)/output:/app/output" \
  website-scraper
```

Or with Docker Compose:

```bash
docker compose up -d --build
```

Open **`http://localhost:5000`** *(use `localhost` or `127.0.0.1`, not `0.0.0.0`, as modern browsers block 0.0.0.0)*. Scraped files appear in `./output` on your machine.

Prebuilt images are also published for Intel/AMD and Apple Silicon:

```bash
docker pull devansh-kumar-saini/website-scraper:latest   # Docker Hub
docker pull ghcr.io/devansh-kumar-saini/web-scrapper:latest  # GitHub Container Registry
```

See [docs/DOCKER.md](docs/DOCKER.md) for the full Docker guide.

---

## Web UI Dashboard

The Web UI provides complete visual control over all scraping capabilities:

1. **Crawl Setup**:
   - Seed URLs input with quick test samples.
   - Crawl limits: depth (0 to 5), max pages cap, concurrency workers, and request delay.
   - Domain boundaries: stay on seed domain(s) or allow external links.
   - Sitemap integration: automatic detection or custom sitemap URL.
   - Phase 6 Resilience controls: Incremental delta crawling, SQLite checkpoint queue, adaptive rate limiting, and optional Dead-Letter Queue (DLQ).
   - Impersonation & proxy: TLS fingerprinting (`chrome`, `safari`, `firefox`) and HTTP/SOCKS proxy routing.

2. **Extraction Settings**:
   - Primary output formats: Text, Markdown, JSON, JSONL, CSV, SQLite.
   - Content and exclusion selectors (CSS or XPath).
   - Structured schema mapping (custom JSON field definitions).
   - RAG chunking: character chunk size and chunk overlap.

3. **URL Filters & Scope**:
   - Include / exclude URL patterns (supports shell globs and `re:` regular expressions).
   - Interactive live URL test box to test patterns before running.

4. **Media Extractor**:
   - Enable media cataloging and local downloading.
   - Filter by asset types: Images, PDFs, Documents, Presentations, Videos.
   - Select modes: Scraped pages + Media, or Media-only.

5. **Live Monitor & Terminal**:
   - Real-time page discovery and progress telemetry over SSE.
   - Color-coded log streaming with search and log level filters.
   - Dead-Letter Queue (DLQ) retry panel: view categorized failures (HTTP 429, 5xx, timeouts) and retry failed URLs with 1 click.

6. **Saved Pages & Output Catalog**:
   - In-app preview of saved Markdown, text, and JSON documents.
   - Media gallery and manifest browser.
   - 1-click ZIP export with on-the-fly format conversion (Markdown, JSON, CSV, SQLite).

---

## Instant Single-Page Scrape API

Start the server (`python main.py`) and scrape one URL synchronously — no crawl job, no polling:

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "format": "markdown"}'
```

The response is `text/markdown` by default. Set `"format": "json"` for the full structured payload, `"text"` for readable text, or `"html"` for the extracted container HTML (served as plain text).

GET works too, which is convenient for shell pipelines:

```bash
curl "http://localhost:5000/api/scrape?url=https://example.com&format=markdown" | head -40
curl "http://localhost:5000/api/scrape?url=https://example.com&format=json" | jq .title
```

Request parameters:

| Field | Description | Default |
|---|---|---|
| `url` | Page to scrape (required) | — |
| `format` | `markdown`, `text`, `json`, `html` | `markdown` |
| `render_js` | Render with local Playwright Chromium | `false` |
| `selector` / `target_selector` | Extract only inside this CSS or XPath selector | Whole page |
| `exclude_selectors` | String or list of CSS/XPath selectors to strip | None |
| `schema` | Object or JSON string mapping custom fields to selectors | None |
| `chunk_size` / `chunk_overlap` | Include overlapping chunks in JSON output | `0` / `400` |
| `respect_robots` | Enforce `robots.txt` | `true` |

Error responses are JSON with `error` and `code` fields (`robots_disallowed`, `non_html`, `fetch_failed`, `timeout`).

### Batch crawl API

The REST endpoints driving the Web UI:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/scrape/start` | POST | Start a background crawl |
| `/api/scrape/stop` | POST | Stop the active crawl |
| `/api/scrape/status` | GET | Current job snapshot |
| `/api/scrape/events` | GET | SSE progress/log stream |
| `/api/scrape/failures` | GET | Dead-letter queue failed URLs |
| `/api/jobs/:id/retry-failures` | POST | Requeue and retry DLQ URLs |
| `/api/jobs/:id/resume` | POST | Resume interrupted crawl from checkpoint |
| `/api/results` | GET | List saved pages from `index.json` |
| `/api/results/file` | GET | Preview one saved file |
| `/api/results/download` | GET | Download output directory as ZIP (`?format=md\|txt\|json\|jsonl\|csv\|sqlite` converts first) |
| `/api/results/clear` | POST | Delete files in the output directory |

`POST /api/scrape/start` accepts:
- `urls`, `sitemap`, `sitemap_url`
- `depth`, `max_pages`, `same_domain`, `concurrency`, `delay`
- `format`, `target_selector`, `exclude_selectors`, `schema`
- `chunk_size`, `chunk_overlap`, `include_patterns`, `exclude_patterns`
- `incremental`, `checkpoint`, `adaptive_rate_limit`, `max_retries`, `dlq`
- `extract_media`, `media_mode`, `download_media`, `media_types`
- `render_js`, `impersonate`, `proxy`, `webhook_url`

---

## Python Library

The core crawler is also importable directly in Python:

```python
from Backend import Crawler, scrape_url

# Instant single-page scrape
document = scrape_url(
    "https://docs.example.com/api",
    target_selector="article",
    exclude_selectors=[".advertisement"],
    schema={
        "title": "h1",
        "price": {"selector": ".price", "attr": "content"},
        "images": {"selector": ".gallery img", "attr": "src", "all": True},
    },
)
print(document.markdown)
print(document.schema)
print(document.to_dict())

# Multi-page crawl
crawler = Crawler(max_depth=2, max_pages=50, same_domain=True, logger=__import__("logging").getLogger())
for page in crawler.crawl(["https://example.com"]):
    print(page.depth, page.url, page.title)
```

---

## Output Formats

Every page gets a structured record with these fields:

```json
{
  "url": "https://docs.example.com/api",
  "title": "API Documentation",
  "description": "Meta description",
  "author": "Jane Doe",
  "published_time": "2026-01-15T00:00:00Z",
  "canonical_url": "https://docs.example.com/api",
  "markdown": "# API Documentation\n\n...",
  "text": "API Documentation...",
  "html": "<article>...</article>",
  "links": ["https://docs.example.com/auth"],
  "images": [{"src": "https://docs.example.com/logo.png", "alt": "Logo"}],
  "headings": ["API Documentation", "Authentication"],
  "chunks": [],
  "schema": {"title": "API Documentation", "price": null},
  "word_count": 412,
  "status_code": 200,
  "selector_matched": true
}
```

| Format | Files written |
|---|---|
| `txt` | `<page>.txt` with a metadata header and readable text |
| `md` | `<page>.md` with YAML front matter and GitHub-Flavored Markdown |
| `json` | `<page>.json` with the full structured record |
| `jsonl` | `pages.jsonl`, one JSON record per line |
| `csv` | `pages.csv`, one row per page (lists and schema stored as JSON) |
| `sqlite` | `pages.db` with a `pages` table (query with any SQLite client) |

The output directory also contains `index.json` (manifest of saved pages) and `scrape_log.txt` (crawler events and skipped-resource reasons).

---

## License

MIT — see [LICENSE](LICENSE).
