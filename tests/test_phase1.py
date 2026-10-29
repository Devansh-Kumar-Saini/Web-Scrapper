"""Tests for Phase 1: Markdown, single-page API, filters, selectors, and packaging."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.app import app
from Backend.extractor import PageContent, chunk_text, extract_structured
from Backend.fetcher import Fetcher, NonHtmlContent, RobotsDisallowed
from Backend.filters import URLFilter, matches_pattern, parse_patterns, parse_selectors
from Backend.writer import OutputWriter

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>API Documentation</title>
  <meta name="description" content="Learn the API">
  <meta name="author" content="Jane Doe">
  <meta property="article:published_time" content="2026-01-15T00:00:00Z">
  <link rel="canonical" href="https://docs.example.com/api">
</head>
<body>
  <nav>Menu <a href="/home">Home</a></nav>
  <article>
    <h1>API Documentation</h1>
    <p>Welcome to the <strong>API</strong>. See <a href="/auth">auth</a>.</p>
    <ul><li>One</li><li>Two</li></ul>
    <img src="/logo.png" alt="Logo">
    <div class="advertisement">Buy something</div>
    <h2>Authentication</h2>
    <p>Use a bearer token.</p>
  </article>
  <footer>Footer boilerplate</footer>
</body>
</html>"""


class TestExtraction(unittest.TestCase):
    def test_markdown_metadata_links_and_headings(self):
        document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api")

        self.assertEqual(document.title, "API Documentation")
        self.assertEqual(document.description, "Learn the API")
        self.assertEqual(document.author, "Jane Doe")
        self.assertEqual(document.published_time, "2026-01-15T00:00:00Z")
        self.assertEqual(document.canonical_url, "https://docs.example.com/api")
        self.assertIn("# API Documentation", document.markdown)
        self.assertIn("## Authentication", document.markdown)
        self.assertIn("- One", document.markdown)
        self.assertIn("[auth](https://docs.example.com/auth)", document.markdown)
        self.assertIn("![Logo](https://docs.example.com/logo.png)", document.markdown)
        self.assertIn("https://docs.example.com/auth", document.links)
        self.assertEqual(document.images, [{"src": "https://docs.example.com/logo.png", "alt": "Logo"}])
        self.assertEqual(document.headings, ["API Documentation", "Authentication"])
        self.assertNotIn("Footer boilerplate", document.text)
        self.assertGreater(document.word_count, 0)

    def test_target_and_exclude_selectors(self):
        document = extract_structured(
            SAMPLE_HTML,
            url="https://docs.example.com/api",
            target_selector="article",
            exclude_selectors=[".advertisement"],
        )
        self.assertTrue(document.selector_matched)
        self.assertNotIn("Buy something", document.markdown)
        self.assertNotIn("Footer boilerplate", document.markdown)
        self.assertIn("Welcome to the API", document.text)

    def test_unmatched_selector_falls_back(self):
        document = extract_structured(SAMPLE_HTML, target_selector=".does-not-exist")
        self.assertFalse(document.selector_matched)
        self.assertIn("# API Documentation", document.markdown)

    def test_invalid_selector_raises_value_error(self):
        with self.assertRaises(ValueError):
            extract_structured(SAMPLE_HTML, target_selector="article[[[")
        with self.assertRaises(ValueError):
            extract_structured(SAMPLE_HTML, exclude_selectors=["aside[[["])

    def test_markdown_fallback_without_markdownify(self):
        with patch("Backend.extractor._markdownify", None):
            document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api")
        self.assertIn("# API Documentation", document.markdown)
        self.assertIn("## Authentication", document.markdown)

    def test_chunking(self):
        text = "\n\n".join(f"Paragraph {i} " + ("word " * 30) for i in range(8))
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))
        self.assertEqual(chunk_text("", chunk_size=200), [])

    def test_chunks_are_included_in_structured_output(self):
        document = extract_structured(SAMPLE_HTML, chunk_size=60, chunk_overlap=10)
        self.assertTrue(document.chunks)
        self.assertTrue(all(len(chunk) <= 60 for chunk in document.chunks))


class TestURLFilters(unittest.TestCase):
    def test_include_and_exclude(self):
        url_filter = URLFilter(include_patterns=["*/docs/*"], exclude_patterns=["*api*"])
        self.assertTrue(url_filter.allows("https://example.com/docs/start"))
        self.assertFalse(url_filter.allows("https://example.com/docs/api"))
        self.assertFalse(url_filter.allows("https://example.com/blog/post"))

    def test_plain_text_and_regex_patterns(self):
        self.assertTrue(matches_pattern("https://example.com/accounts/login", "*login*"))
        self.assertTrue(matches_pattern("https://example.com/cart", "cart"))
        self.assertTrue(matches_pattern("https://example.com/docs/123", r"re:/docs/\d+$"))
        self.assertFalse(matches_pattern("https://example.com/docs/abc", r"re:/docs/\d+$"))

    def test_pattern_parsing(self):
        self.assertEqual(parse_patterns("*/docs/*, *login*\n*cart*"), ["*/docs/*", "*login*", "*cart*"])
        self.assertEqual(parse_patterns(["/docs/*", "/blog/*"]), ["/docs/*", "/blog/*"])
        self.assertEqual(parse_patterns("re:/items/\\d{1,3}$"), ["re:/items/\\d{1,3}$"])
        # CSS selector groups keep their commas.
        self.assertEqual(parse_selectors("aside, .advertisement\n.cookie-banner"), ["aside, .advertisement", ".cookie-banner"])


class TestWriterFormats(unittest.TestCase):
    def test_markdown_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = OutputWriter(tmp_dir, output_format="md")
            document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api")
            filename = writer.save_document(document, depth=1)
            writer.finalize()

            self.assertTrue(filename.endswith(".md"))
            content = (Path(tmp_dir) / filename).read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"))
            self.assertIn('title: "API Documentation"', content)
            self.assertIn('url: "https://docs.example.com/api"', content)
            self.assertIn("# API Documentation", content)
            manifest = json.loads((Path(tmp_dir) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest[0]["format"], "md")

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = OutputWriter(tmp_dir, output_format="json")
            document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api")
            filename = writer.save_document(document, depth=2)
            writer.finalize()

            record = json.loads((Path(tmp_dir) / filename).read_text(encoding="utf-8"))
            self.assertEqual(record["title"], "API Documentation")
            self.assertEqual(record["depth"], 2)
            self.assertEqual(record["images"][0]["alt"], "Logo")

    def test_jsonl_output_appends_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = OutputWriter(tmp_dir, output_format="jsonl")
            writer.save_document(extract_structured(SAMPLE_HTML, url="https://a.example/one"), 0)
            writer.save_document(extract_structured(SAMPLE_HTML, url="https://a.example/two"), 1)
            writer.finalize()

            lines = (Path(tmp_dir) / "pages.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["url"], "https://a.example/two")

    def test_txt_output_remains_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = OutputWriter(tmp_dir)
            filename = writer.save_page("https://example.com/test", "Test Page", "Body text", 1)
            writer.finalize()
            content = (Path(tmp_dir) / filename).read_text(encoding="utf-8")
            self.assertIn("Title: Test Page", content)
            self.assertIn("Body text", content)

    def test_invalid_format_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                OutputWriter(tmp_dir, output_format="xml")


class TestFetcher(unittest.TestCase):
    def _session(self, *, content_type="application/pdf", status=200, text="body"):
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        response.headers = {"Content-Type": content_type}
        response.text = text
        response.url = "https://example.com/file"
        session.get.return_value = response
        return session

    def test_non_html_is_rejected(self):
        fetcher = Fetcher(session=self._session(), respect_robots=False, delay=0)
        with self.assertRaises(NonHtmlContent):
            fetcher.fetch("https://example.com/file")

    def test_robots_is_enforced(self):
        session = MagicMock()
        robots_response = MagicMock(status_code=200, text="User-agent: *\nDisallow: /private\n")
        session.get.return_value = robots_response
        fetcher = Fetcher(session=session, respect_robots=True, delay=0)
        self.assertTrue(fetcher.can_fetch("https://example.com/public"))
        self.assertFalse(fetcher.can_fetch("https://example.com/private"))
        with self.assertRaises(RobotsDisallowed):
            fetcher.fetch("https://example.com/private")


class TestScrapeAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_markdown_response(self):
        document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api")
        with patch("Backend.app.scrape_url", return_value=document) as mock_scrape:
            response = self.client.post(
                "/api/scrape",
                json={"url": "https://docs.example.com/api", "format": "markdown"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.content_type)
        self.assertIn("# API Documentation", response.get_data(as_text=True))
        self.assertEqual(response.headers["X-Word-Count"], str(document.word_count))
        mock_scrape.assert_called_once()

    def test_json_response_and_options(self):
        document = extract_structured(SAMPLE_HTML, url="https://docs.example.com/api", chunk_size=100)
        with patch("Backend.app.scrape_url", return_value=document) as mock_scrape:
            response = self.client.post(
                "/api/scrape",
                json={
                    "url": "https://docs.example.com/api",
                    "format": "json",
                    "render_js": True,
                    "selector": "article",
                    "exclude_selectors": [".advertisement"],
                    "chunk_size": 100,
                    "respect_robots": False,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["title"], "API Documentation")
        self.assertIn("markdown", payload)
        kwargs = mock_scrape.call_args.kwargs
        self.assertTrue(kwargs["render_js"])
        self.assertEqual(kwargs["target_selector"], "article")
        self.assertEqual(kwargs["exclude_selectors"], [".advertisement"])
        self.assertEqual(kwargs["chunk_size"], 100)
        self.assertFalse(kwargs["respect_robots"])

    def test_get_support(self):
        document = PageContent(url="https://example.com", text="hello")
        with patch("Backend.app.scrape_url", return_value=document):
            response = self.client.get("/api/scrape", query_string={"url": "https://example.com", "format": "text"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "hello")

    def test_invalid_url(self):
        response = self.client.post("/api/scrape", json={"url": "not-a-url"})
        self.assertEqual(response.status_code, 400)

    def test_error_mapping(self):
        with patch("Backend.app.scrape_url", side_effect=RobotsDisallowed("blocked", "https://x.test")):
            self.assertEqual(self.client.post("/api/scrape", json={"url": "https://x.test"}).status_code, 403)
        with patch("Backend.app.scrape_url", side_effect=NonHtmlContent("pdf", "https://x.test")):
            self.assertEqual(self.client.post("/api/scrape", json={"url": "https://x.test"}).status_code, 415)
        with patch("Backend.app.scrape_url", side_effect=ValueError("bad selector")):
            self.assertEqual(self.client.post("/api/scrape", json={"url": "https://x.test"}).status_code, 400)

    def test_start_passes_advanced_options(self):
        with patch("Backend.app.job_manager.start_crawl", return_value=(True, "Crawl job started.")) as mock_start:
            response = self.client.post(
                "/api/scrape/start",
                json={
                    "urls": ["https://example.com"],
                    "format": "markdown",
                    "include_patterns": "*/docs/*",
                    "exclude_patterns": ["*login*"],
                    "selector": "article",
                    "exclude_selectors": ".advertisement",
                    "chunk_size": 500,
                },
            )
        self.assertEqual(response.status_code, 200)
        kwargs = mock_start.call_args.kwargs
        self.assertEqual(kwargs["output_format"], "md")
        self.assertEqual(kwargs["include_patterns"], ["*/docs/*"])
        self.assertEqual(kwargs["exclude_patterns"], ["*login*"])
        self.assertEqual(kwargs["target_selector"], "article")
        self.assertEqual(kwargs["exclude_selectors"], [".advertisement"])
        self.assertEqual(kwargs["chunk_size"], 500)

    def test_start_rejects_invalid_selector(self):
        response = self.client.post(
            "/api/scrape/start",
            json={"urls": ["https://example.com"], "selector": "article[[["},
        )
        self.assertEqual(response.status_code, 400)

    def test_start_accepts_ui_output_format_key(self):
        with patch("Backend.app.job_manager.start_crawl", return_value=(True, "ok")) as mock_start:
            response = self.client.post(
                "/api/scrape/start",
                json={"urls": ["https://example.com"], "output_format": "jsonl"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_start.call_args.kwargs["output_format"], "jsonl")


if __name__ == "__main__":
    unittest.main()
