# Website Content Scraper
---

**Build a website content scraper with the following exact specifications:**

## Overview
Create a command-line tool that accepts one or more website URLs, crawls each to a user-defined depth, extracts the readable text content from every page discovered, and saves each page's content as a separate `.txt` file inside an `/output` directory. **No third-party scraping APIs or web services may be used** — only direct HTTP requests and local parsing libraries.

## Tech Stack
- **Language:** Python 3.10+ (preferred) — or Node.js 18+ if you prefer JS. Pick one and state it clearly.
- **HTTP client:** Python `requests` (or Node `axios`/native `fetch`)
- **HTML parsing:** Python `BeautifulSoup4` + `lxml` (or Node `cheerio`)
- **For JS-rendered sites (optional fallback):** Python `playwright` (or Node `puppeteer`). Only use if plain HTTP returns no content; make it optional.
- **CLI:** Python `argparse` (or Node `commander`)
- **No external APIs** — everything must run locally against the target sites directly.

## Functional Requirements

### 1. Input
Support both **interactive prompts** and **CLI flags**:
- One or more URLs (accept a comma-separated list or repeated `--url` flags)
- Depth: integer from `0` to `5` (define 0 = only the given URL, 1 = the given URL + its direct links, etc.)
- Optional: `--max-pages` cap (default 100) to prevent runaway crawls
- Optional: `--same-domain` flag (default ON) — only follow links that share the root domain of the seed URL
- Optional: `--output-dir` (default `./output`)

### 2. Crawling Logic
- Use a **BFS queue** with a visited-URL set to avoid duplicates.
- Track current depth per URL; stop enqueuing when depth limit is reached.
- Normalize URLs: strip fragments (`#...`), resolve relative links against the current page, lowercase the host.
- Skip non-HTML resources (images, PDFs, zip, CSS, JS — check `Content-Type` header and file extension).
- **Politeness:** 1-second delay between requests to the same domain; respect `robots.txt` using Python's `urllib.robotparser` (or Node `robots-parser`).
- Set a realistic `User-Agent` and a request timeout (10s).
- Handle redirects, HTTP errors (4xx/5xx), and timeouts gracefully — log them and continue.

### 3. Content Extraction
For each fetched page:
- Parse HTML and extract:
  - Page `<title>`
  - Source URL
  - Main readable text (strip `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`, `<form>`, and comments)
- Collapse repeated whitespace; preserve paragraph breaks.
- Optionally attempt to locate the main content container (`<article>`, `<main>`, or the densest `<div>`) before falling back to `<body>` — implement a simple heuristic.

### 4. Output
- Create `./output/` if it doesn't exist.
- For each successfully scraped page, write **one `.txt` file**.
- **Filename rule:** derive from the URL path — sanitize to lowercase, replace `/` and special chars with `_`, keep it under 100 chars, append `.txt`. If it collides, append `_2`, `_3`, etc. If the path is empty (root URL), use the domain name.
- **File contents (plain text, structured):**
  ```
  Title: <page title>
  URL: <source url>
  Depth: <depth>
  Scraped: <ISO timestamp>

  ----------------------------------------

  <extracted text>
  ```
- Also write a single `index.json` (or `manifest.txt`) at the root of `output/` listing every saved file with its source URL, title, depth, and byte size.

### 5. Logging & Feedback
- Print progress to the console: `[depth 1] fetching https://... -> output/example_page.txt`
- Print a **final summary**: total pages crawled, pages saved, pages skipped (with reasons), total files written, and elapsed time.
- Write a `scrape_log.txt` in `output/` with all warnings/errors.

### 6. Error Handling
- Invalid URL → warn, skip, continue.
- Network failure → retry once after 2s, then log and skip.
- Empty extraction → still save the file with a note `[No text content extracted]`.
- Never crash the whole run because of one bad page.

### 7. Structure
Organize the code into clear modules:
- `main.py` — CLI entry, argument parsing, orchestration
- `crawler.py` — BFS queue, fetching, link discovery
- `extractor.py` — HTML → text
- `writer.py` — file naming, saving, manifest
- `config.py` — constants (timeout, delay, UA, depth limits)
- `requirements.txt` (or `package.json`)
- A short `README.md` explaining installation and usage with 2–3 example commands.

### 8. Example Usage
```
python main.py --url https://example.com --depth 1
python main.py --url https://a.com,https://b.com --depth 2 --max-pages 50
python main.py   # interactive mode: prompts for URLs, depth, options
```

## Constraints
- **Do not use any paid or hosted scraping API** (no ScrapingBee, Apify, Firecrawl, etc.).
- Everything must run locally.
- All dependencies must be installable via `pip install -r requirements.txt` (or `npm install`).
- Make depth and same-domain behavior configurable but sensible by default.
- Code should be clean, commented, and production-friendly (type hints in Python, modular functions).

Deliver the full working project: all source files, `requirements.txt`/`package.json`, and `README.md`. Include a quick test run against `https://example.com` with depth 1 to demonstrate it works.

---