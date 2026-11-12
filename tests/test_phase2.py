"""Comprehensive test suite for Phase 2: Performance & Engine Upgrades."""

import gzip
import io
import json
import logging
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from Backend.app import app
from Backend.cli import parse_args, run
from Backend.crawler import Crawler, Page
from Backend.fetcher import Fetcher, FetchResult
from Backend.sitemap import discover_sitemap_urls, fetch_sitemap_urls, parse_sitemap_xml


class TestSitemapParser(unittest.TestCase):
    def test_parse_urlset_standard(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/page1</loc>
                <lastmod>2026-01-01</lastmod>
            </url>
            <url>
                <loc>https://example.com/page2</loc>
            </url>
        </urlset>"""
        pages, sub_sitemaps = parse_sitemap_xml(xml)
        self.assertEqual(pages, ["https://example.com/page1", "https://example.com/page2"])
        self.assertEqual(sub_sitemaps, [])

    def test_parse_sitemap_index(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap>
                <loc>https://example.com/sitemap-1.xml</loc>
            </sitemap>
            <sitemap>
                <loc>https://example.com/sitemap-2.xml.gz</loc>
            </sitemap>
        </sitemapindex>"""
        pages, sub_sitemaps = parse_sitemap_xml(xml)
        self.assertEqual(pages, [])
        self.assertEqual(
            sub_sitemaps,
            ["https://example.com/sitemap-1.xml", "https://example.com/sitemap-2.xml.gz"],
        )

    def test_parse_malformed_xml_regex_fallback(self):
        bad_xml = "<urlset><url><loc>https://example.com/broken</loc><unclosed></urlset>"
        pages, sub_sitemaps = parse_sitemap_xml(bad_xml)
        self.assertEqual(pages, ["https://example.com/broken"])

    def test_discover_sitemap_from_robots(self):
        robots = "User-agent: *\nDisallow: /admin\nSitemap: https://example.com/custom_sitemap.xml\n"
        discovered = discover_sitemap_urls("https://example.com", robots_content=robots)
        self.assertIn("https://example.com/custom_sitemap.xml", discovered)

    def test_fetch_sitemap_urls_with_mock_and_gzip(self):
        session = MagicMock()
        resp_index = MagicMock(status_code=200)
        resp_index.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sub.xml.gz</loc></sitemap>
        </sitemapindex>"""

        sub_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/gz-page</loc></url>
        </urlset>"""
        compressed = gzip.compress(sub_xml)
        resp_sub = MagicMock(status_code=200, content=compressed)

        session.get.side_effect = [resp_index, resp_sub]

        urls = fetch_sitemap_urls("https://example.com/sitemap.xml", session=session)
        self.assertEqual(urls, ["https://example.com/gz-page"])


class TestFetcherPhase2(unittest.TestCase):
    def test_fetcher_with_impersonation(self):
        logger = logging.getLogger("test_fetcher")
        fetcher = Fetcher(logger=logger, impersonate="chrome")
        self.assertTrue(fetcher.is_curl_cffi)
        self.assertIn("User-Agent", fetcher.session.headers)
        fetcher.close()

    def test_fetcher_with_proxy(self):
        logger = logging.getLogger("test_fetcher")
        fetcher = Fetcher(logger=logger, proxy="http://127.0.0.1:8888")
        self.assertEqual(fetcher.session.proxies.get("http"), "http://127.0.0.1:8888")
        fetcher.close()

    def test_fetcher_rotate_user_agent(self):
        logger = logging.getLogger("test_fetcher")
        fetcher = Fetcher(logger=logger, rotate_user_agent=True)
        # Mock session.get to verify User-Agent rotation
        mock_resp = MagicMock(status_code=200, text="<html><body>OK</body></html>")
        mock_resp.headers = {"Content-Type": "text/html"}
        fetcher.session.get = MagicMock(return_value=mock_resp)
        fetcher._robots_for = MagicMock(return_value=MagicMock(can_fetch=lambda ua, u: True))

        result = fetcher.fetch("https://example.com")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(len(fetcher.session.headers["User-Agent"]) > 0)
        fetcher.close()

    def test_polite_per_domain_pacing(self):
        logger = logging.getLogger("test_pacing")
        fetcher = Fetcher(logger=logger, delay=0.1)

        t0 = threading.Thread(target=fetcher._wait_for_domain, args=("domain1.com",))
        t1 = threading.Thread(target=fetcher._wait_for_domain, args=("domain2.com",))
        t0.start()
        t1.start()
        t0.join()
        t1.join()

        # Both domains should have independent next_request timestamps
        self.assertIn("domain1.com", fetcher._last_request)
        self.assertIn("domain2.com", fetcher._last_request)
        fetcher.close()

    def test_zero_delay_skips_waiting(self):
        logger = logging.getLogger("test_zero_delay")
        fetcher = Fetcher(logger=logger, delay=0.0)
        fetcher._wait_for_domain("fast.com")
        # With zero delay, nothing is recorded in _last_request and no sleep happens
        self.assertNotIn("fast.com", fetcher._last_request)
        fetcher.close()


class _FakeSession:
    """Minimal stand-in for ``requests.Session`` used by ``Fetcher._get_session``."""

    instances: list["_FakeSession"] = []
    calls: list[str] = []

    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.proxies = {}
        self.mounted = []
        self.closed = False
        _FakeSession.instances.append(self)

    def mount(self, prefix, adapter):
        self.mounted.append(prefix)

    def get(self, url, timeout=None, allow_redirects=True):
        _FakeSession.calls.append(url)
        return MagicMock(status_code=200, text="User-agent: *\nAllow: /\n")

    def close(self):
        self.closed = True


class TestFetcherRobotsLocking(unittest.TestCase):
    """Regression tests for the robots.txt locking used by concurrent crawls."""

    def setUp(self):
        _FakeSession.instances = []
        _FakeSession.calls = []

    def _fetcher(self):
        return Fetcher(respect_robots=True, delay=0)

    def test_robots_lookup_does_not_deadlock(self):
        # Regression: _robots_for() held Fetcher._lock while _get_session()
        # tried to acquire the same lock, hanging every crawl (and CI) forever.
        with patch("Backend.fetcher.requests.Session", _FakeSession):
            fetcher = self._fetcher()
            outcome: dict[str, bool] = {}
            worker = threading.Thread(
                target=lambda: outcome.update(allowed=fetcher.can_fetch("https://example.com/page"))
            )
            worker.start()
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive(), "robots.txt lookup deadlocked")
            self.assertTrue(outcome.get("allowed"))
            fetcher.close()

    def test_robots_cached_per_origin(self):
        with patch("Backend.fetcher.requests.Session", _FakeSession):
            fetcher = self._fetcher()
            self.assertTrue(fetcher.can_fetch("https://example.com/one"))
            self.assertTrue(fetcher.can_fetch("https://example.com/two"))
            self.assertEqual(len(_FakeSession.calls), 1)

            self.assertTrue(fetcher.can_fetch("https://other.example.org/page"))
            self.assertEqual(len(_FakeSession.calls), 2)
            fetcher.close()

    def test_robots_fetch_concurrent_origins(self):
        with patch("Backend.fetcher.requests.Session", _FakeSession):
            fetcher = self._fetcher()
            errors: list[BaseException] = []

            def check(url: str) -> None:
                try:
                    fetcher.can_fetch(url)
                except BaseException as exc:  # pragma: no cover - surfaced by assertion
                    errors.append(exc)

            threads = [
                threading.Thread(target=check, args=(url,))
                for url in (
                    "https://a.example.com/page",
                    "https://b.example.com/page",
                    "https://c.example.com/page",
                )
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertFalse(any(t.is_alive() for t in threads), "concurrent robots lookups deadlocked")
            self.assertEqual(errors, [])
            self.assertEqual(len(_FakeSession.calls), 3)
            fetcher.close()


class TestConcurrentCrawler(unittest.TestCase):
    def test_concurrent_crawl_success(self):
        logger = logging.getLogger("test_crawler")
        fetcher = MagicMock()

        def mock_fetch(url):
            if url in {"https://example.com", "https://example.com/"}:
                html = '<html><head><title>Home</title></head><body><p>Plenty of text on home page to avoid playwright fallback</p><a href="/page1">P1</a><a href="/page2">P2</a></body></html>'
            elif url == "https://example.com/page1":
                html = "<html><head><title>Page 1</title></head><body>Content 1 with plenty of words to avoid playwright</body></html>"
            elif url == "https://example.com/page2":
                html = "<html><head><title>Page 2</title></head><body>Content 2 with plenty of words to avoid playwright</body></html>"
            else:
                html = "<html><body>Empty</body></html>"
            return FetchResult(requested_url=url, final_url=url, html=html, status_code=200, content_type="text/html")

        fetcher.fetch.side_effect = mock_fetch
        fetcher.session = MagicMock()

        crawler = Crawler(
            max_depth=1,
            max_pages=5,
            same_domain=True,
            logger=logger,
            concurrency=3,
            fetcher=fetcher,
        )

        pages = list(crawler.crawl(["https://example.com"]))
        self.assertEqual(len(pages), 3)
        urls = {p.url for p in pages}
        self.assertEqual(urls, {"https://example.com/", "https://example.com/page1", "https://example.com/page2"})

    def test_crawler_with_sitemap(self):
        logger = logging.getLogger("test_crawler")
        fetcher = MagicMock()
        fetcher.session = MagicMock()
        fetcher.fetch.return_value = FetchResult(
            requested_url="https://example.com/sitemap-p1",
            final_url="https://example.com/sitemap-p1",
            html="<html><head><title>Sitemap P1</title></head><body>Real body content here</body></html>",
            status_code=200,
            content_type="text/html",
        )

        with patch("Backend.crawler.fetch_sitemap_urls", return_value=["https://example.com/sitemap-p1"]):
            crawler = Crawler(
                max_depth=0,
                max_pages=5,
                same_domain=True,
                logger=logger,
                concurrency=2,
                sitemap_url="https://example.com/sitemap.xml",
                fetcher=fetcher,
            )
            pages = list(crawler.crawl(["https://example.com"]))
            urls = {p.url for p in pages}
            self.assertIn("https://example.com/sitemap-p1", urls)

    def test_crawler_with_page_processor_parallel_pipeline(self):
        logger = logging.getLogger("test_crawler")
        fetcher = MagicMock()
        fetcher.session = MagicMock()
        fetcher.fetch.return_value = FetchResult(
            requested_url="https://example.com/test",
            final_url="https://example.com/test",
            html="<html><head><title>Test Page</title></head><body><h1>Content</h1></body></html>",
            status_code=200,
            content_type="text/html",
        )

        def mock_processor(url: str, html: str, depth: int):
            return {"processed_url": url, "has_content": True}

        crawler = Crawler(
            max_depth=0,
            max_pages=1,
            same_domain=True,
            logger=logger,
            concurrency=1,
            fetcher=fetcher,
            page_processor=mock_processor,
        )
        pages = list(crawler.crawl(["https://example.com/test"]))
        self.assertEqual(len(pages), 1)
        self.assertIsNotNone(pages[0].extracted_document)
        self.assertEqual(pages[0].extracted_document["processed_url"], "https://example.com/test")
        self.assertTrue(pages[0].extracted_document["has_content"])


class TestCLIPipeAndDryRun(unittest.TestCase):
    @patch("Backend.cli.Crawler")
    def test_cli_dry_run_stdout(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.url_filter.excluded_by.return_value = None
        mock_crawler_cls.return_value = mock_inst

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = run(parse_args(["--url", "https://example.com/dry", "--dry-run"]))
            self.assertEqual(ret, 0)
        output = captured_stdout.getvalue()
        self.assertIn("Dry run:", output)
        self.assertIn("https://example.com/dry", output)

    @patch("Backend.cli.Crawler")
    def test_cli_dry_run_json(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.url_filter.excluded_by.return_value = None
        mock_crawler_cls.return_value = mock_inst

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = run(parse_args(["--url", "https://example.com/dry", "--dry-run", "--json"]))
            self.assertEqual(ret, 0)
        output = captured_stdout.getvalue()
        data = json.loads(output)
        self.assertTrue(data.get("dry_run"))
        self.assertIn("https://example.com/dry", data.get("target_urls"))

    @patch("Backend.cli.Crawler")
    def test_cli_stdout_markdown_pipe(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_page = Page("https://example.com/p1", 0, "Test Title", "<html><body><h1>Hello World</h1><p>Test</p></body></html>")
        mock_inst.crawl.return_value = [mock_page]
        mock_inst.skipped_reasons = []
        mock_crawler_cls.return_value = mock_inst

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = run(parse_args(["--url", "https://example.com/p1", "--stdout", "--format", "md"]))
            self.assertEqual(ret, 0)
        output = captured_stdout.getvalue()
        self.assertIn("# Hello World", output)

    @patch("Backend.cli.Crawler")
    def test_cli_json_pipe(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_page = Page("https://example.com/p1", 0, "Test Title", "<html><head><title>Test Title</title></head><body><h1>Hello JSON</h1><p>Words words words words words</p></body></html>")
        mock_inst.crawl.return_value = [mock_page]
        mock_inst.skipped_reasons = []
        mock_crawler_cls.return_value = mock_inst

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = run(parse_args(["--url", "https://example.com/p1", "--json"]))
            self.assertEqual(ret, 0)
        data = json.loads(captured_stdout.getvalue())
        self.assertEqual(data["url"], "https://example.com/p1")
        self.assertEqual(data["title"], "Test Title")

    def test_cli_config_file_loading(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
            f.write(json.dumps({"depth": 3, "format": "jsonl", "concurrency": 8, "delay": 0.05}))
            f.flush()
            args = parse_args(["--config", f.name, "--url", "https://example.com"])
            self.assertEqual(args.depth, 3)
            self.assertEqual(args.format, "jsonl")
            self.assertEqual(args.concurrency, 8)
            self.assertEqual(args.delay, 0.05)

    def test_cli_delay_argument(self):
        args = parse_args(["--url", "https://example.com", "--delay", "0.5"])
        self.assertEqual(args.delay, 0.5)


class TestAppPhase2Endpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("Backend.app.job_manager.start_crawl")
    def test_start_with_phase2_options(self, mock_start):
        mock_start.return_value = (True, "started")
        payload = {
            "urls": "https://example.com",
            "concurrency": 8,
            "delay": 0.1,
            "sitemap": True,
            "sitemap_url": "https://example.com/sitemap.xml",
            "impersonate": "safari",
            "proxy": "http://127.0.0.1:8080",
        }
        resp = self.client.post("/api/scrape/start", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["config"]["concurrency"], 8)
        self.assertEqual(data["config"]["delay"], 0.1)
        self.assertTrue(data["config"]["sitemap"])
        self.assertEqual(data["config"]["impersonate"], "safari")
        self.assertEqual(data["config"]["proxy"], "http://127.0.0.1:8080")
        self.assertTrue(data["config"]["sitemap"])
        self.assertEqual(data["config"]["impersonate"], "safari")
        self.assertEqual(data["config"]["proxy"], "http://127.0.0.1:8080")

    @patch("Backend.app.scrape_url")
    def test_scrape_with_impersonate_and_proxy(self, mock_scrape):
        mock_doc = MagicMock()
        mock_doc.url = "https://example.com"
        mock_doc.status_code = 200
        mock_doc.markdown = "# Hello"
        mock_doc.text = "Hello"
        mock_doc.html = "<h1>Hello</h1>"
        mock_doc.to_dict.return_value = {"url": "https://example.com", "title": "Hello", "markdown": "# Hello"}
        mock_scrape.return_value = mock_doc

        resp = self.client.post("/api/scrape", json={
            "url": "https://example.com",
            "format": "markdown",
            "impersonate": "chrome",
            "proxy": "http://127.0.0.1:8080",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Hello", resp.get_data(as_text=True))
        mock_scrape.assert_called_once()
        self.assertEqual(mock_scrape.call_args[1]["impersonate"], "chrome")
        self.assertEqual(mock_scrape.call_args[1]["proxy"], "http://127.0.0.1:8080")


if __name__ == "__main__":
    unittest.main()
