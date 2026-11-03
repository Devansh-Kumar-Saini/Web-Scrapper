"""Tests for Phase 3: webhook callbacks and download-time format conversion."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.app import JobManager, JobState, app
from Backend.cli import parse_args, run
from Backend.exporter import build_results_zip, normalize_format, parse_saved_pages
from Backend.extractor import PageContent
from Backend.webhook import build_payload, deliver_webhook, validate_webhook_url
from Backend.writer import OutputWriter

SAMPLE_HTML = """<html><head><title>Docs</title></head><body>
<main><h1>Docs</h1><p>Hello <strong>world</strong>.</p></main>
</body></html>"""


def _document(url="https://example.com/docs", title="Docs") -> PageContent:
    return PageContent(
        url=url,
        title=title,
        description="Docs page",
        markdown="# Docs\n\nHello **world**.",
        text="Docs\n\nHello world.",
        html="<main><h1>Docs</h1><p>Hello world.</p></main>",
        links=[url],
        headings=["Docs"],
        word_count=3,
    )


class TestWebhookHelpers(unittest.TestCase):
    def test_validate_webhook_url(self):
        self.assertEqual(validate_webhook_url(""), "")
        self.assertEqual(validate_webhook_url(" https://hooks.test/ingest "), "https://hooks.test/ingest")
        with self.assertRaises(ValueError):
            validate_webhook_url("ftp://hooks.test/ingest")
        with self.assertRaises(ValueError):
            validate_webhook_url("not-a-url")

    def test_build_payload_shape(self):
        payload = build_payload(
            event="crawl.completed",
            status="completed",
            urls=["https://example.com"],
            stats={"pages_crawled": 2, "pages_saved": 2},
            output_dir="./output",
            pages=[{"url": "https://example.com", "file": "example.md"}],
        )
        self.assertEqual(payload["event"], "crawl.completed")
        self.assertEqual(payload["stats"]["pages_saved"], 2)
        self.assertEqual(payload["pages"][0]["file"], "example.md")
        self.assertIsNone(payload["error"])
        self.assertTrue(payload["started_at"])

    def test_deliver_webhook_success_and_failure(self):
        response = MagicMock(status_code=204)
        with patch("Backend.webhook.requests.post", return_value=response) as mock_post:
            ok, _ = deliver_webhook("https://hooks.test/ingest", {"event": "crawl.completed"})
        self.assertTrue(ok)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["headers"]["X-Webhook-Event"], "crawl.completed")

        failing = MagicMock(status_code=500)
        with patch("Backend.webhook.requests.post", return_value=failing):
            ok, message = deliver_webhook("https://hooks.test/ingest", {"event": "crawl.completed"})
        self.assertFalse(ok)
        self.assertIn("500", message)

    def test_deliver_webhook_network_error_does_not_raise(self):
        import requests

        with patch("Backend.webhook.requests.post", side_effect=requests.RequestException("boom")):
            ok, message = deliver_webhook("https://hooks.test/ingest", {})
        self.assertFalse(ok)
        self.assertIn("boom", message)

    def test_job_manager_sends_summary_payload(self):
        manager = JobManager()
        manager.state = JobState(
            status="completed",
            urls=["https://example.com"],
            output_dir="./output",
            webhook_url="https://hooks.test/ingest",
            pages_crawled=4,
            pages_saved=3,
            pages_skipped=1,
            started_at_iso="2026-01-01T00:00:00+00:00",
            finished_at_iso="2026-01-01T00:00:10+00:00",
            recent_pages=[{"url": "https://example.com", "file": "example.md"}],
        )
        with patch("Backend.app.deliver_webhook", return_value=(True, "ok")) as mock_deliver:
            manager._notify_webhook("crawl.completed", "completed")
        payload = mock_deliver.call_args.args[1]
        self.assertEqual(payload["event"], "crawl.completed")
        self.assertEqual(payload["stats"]["pages_crawled"], 4)
        self.assertEqual(payload["pages"][0]["file"], "example.md")
        mock_deliver.assert_called_once()


class TestWebhookAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_start_passes_webhook_url(self):
        with patch("Backend.app.job_manager.start_crawl", return_value=(True, "ok")) as mock_start:
            response = self.client.post(
                "/api/scrape/start",
                json={"urls": ["https://example.com"], "webhook_url": "https://hooks.test/ingest"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_start.call_args.kwargs["webhook_url"], "https://hooks.test/ingest")
        self.assertEqual(response.get_json()["config"]["webhook_url"], "https://hooks.test/ingest")

    def test_start_rejects_invalid_webhook(self):
        response = self.client.post(
            "/api/scrape/start",
            json={"urls": ["https://example.com"], "webhook_url": "ftp://nope"},
        )
        self.assertEqual(response.status_code, 400)

    def test_start_rejects_invalid_sitemap_url(self):
        response = self.client.post(
            "/api/scrape/start",
            json={"urls": ["https://example.com"], "sitemap_url": "not-a-url"},
        )
        self.assertEqual(response.status_code, 400)


class TestParityOptions(unittest.TestCase):
    """Web UI/API and CLI must expose the same crawl options."""

    def setUp(self):
        self.client = app.test_client()

    def test_start_accepts_sitemap_url_without_seed_urls(self):
        with patch("Backend.app.job_manager.start_crawl", return_value=(True, "ok")) as mock_start:
            response = self.client.post(
                "/api/scrape/start",
                json={"sitemap_url": "https://example.com/sitemap.xml"},
            )
        self.assertEqual(response.status_code, 200)
        kwargs = mock_start.call_args.kwargs
        self.assertEqual(kwargs["urls"], [])
        self.assertEqual(kwargs["sitemap_url"], "https://example.com/sitemap.xml")

    def test_start_passes_render_js_and_dry_run(self):
        with patch("Backend.app.job_manager.start_crawl", return_value=(True, "ok")) as mock_start:
            response = self.client.post(
                "/api/scrape/start",
                json={
                    "urls": ["https://example.com"],
                    "render_js": True,
                    "dry_run": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        kwargs = mock_start.call_args.kwargs
        self.assertTrue(kwargs["render_js"])
        self.assertTrue(kwargs["dry_run"])
        config = response.get_json()["config"]
        self.assertTrue(config["render_js"])
        self.assertTrue(config["dry_run"])

    def test_discover_dry_run_respects_filters_and_cap(self):
        manager = JobManager()
        crawler = MagicMock()
        crawler.session = object()
        crawler.skipped_reasons = []
        crawler.url_filter.excluded_by.side_effect = (
            lambda url: "excluded-pattern" if "admin" in url else None
        )

        sitemap_hits = [
            "https://example.com/a",
            "https://example.com/admin",
            "https://example.com/b",
            "https://example.com/c",
        ]
        with patch("Backend.app.fetch_sitemap_urls", return_value=sitemap_hits):
            targets = manager._discover_dry_run_urls(
                crawler,
                ["https://example.com"],
                sitemap=False,
                sitemap_url="https://example.com/sitemap.xml",
                max_pages=3,
            )

        self.assertEqual(
            targets,
            ["https://example.com", "https://example.com/a", "https://example.com/b"],
        )
        self.assertTrue(any("admin" in reason for reason in crawler.skipped_reasons))

    def test_cli_parse_render_js_flag(self):
        args = parse_args(["--url", "https://example.com", "--render-js"])
        self.assertTrue(args.render_js)

    @patch("Backend.cli.Crawler")
    def test_cli_run_passes_render_js_to_crawler(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.url_filter.excluded_by.return_value = None
        mock_crawler_cls.return_value = mock_inst

        with patch("sys.stdout", io.StringIO()):
            ret = run(parse_args(["--url", "https://example.com/dry", "--dry-run", "--render-js"]))

        self.assertEqual(ret, 0)
        self.assertTrue(mock_crawler_cls.call_args.kwargs["render_js"])

    @patch("Backend.app.Crawler")
    def test_dry_run_crawls_and_discovers_links_without_saving(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.skipped_reasons = []
        p1 = MagicMock(url="https://example.com", depth=0, title="Home")
        p2 = MagicMock(url="https://example.com/about", depth=1, title="About")
        p3 = MagicMock(url="https://example.com/contact", depth=1, title="Contact")
        mock_inst.crawl.return_value = [p1, p2, p3]
        mock_crawler_cls.return_value = mock_inst

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager()
            manager._run_crawler_worker(
                urls=["https://example.com"],
                depth=2,
                max_pages=10,
                same_domain=True,
                output_dir_str=temp_dir,
                dry_run=True,
            )
            snapshot = manager.get_snapshot()

            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["pages_crawled"], 3)
            self.assertEqual(snapshot["pages_saved"], 0)
            self.assertEqual(
                snapshot["discovered_urls"],
                ["https://example.com", "https://example.com/about", "https://example.com/contact"],
            )
            # Verify no page body files or index.json were written to the output dir
            saved_pages = [f for f in Path(temp_dir).glob("*") if f.name != "scrape_log.txt"]
            self.assertEqual(len(saved_pages), 0)

    @patch("Backend.cli.Crawler")
    def test_cli_dry_run_crawls_multiple_pages(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.skipped_reasons = []
        mock_inst.crawl.return_value = [
            MagicMock(url="https://example.com", depth=0),
            MagicMock(url="https://example.com/sub", depth=1),
        ]
        mock_crawler_cls.return_value = mock_inst

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = run(parse_args(["--url", "https://example.com", "--dry-run", "--json"]))
            self.assertEqual(ret, 0)
        data = json.loads(captured_stdout.getvalue())
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["target_urls"], ["https://example.com", "https://example.com/sub"])

    def test_subscriber_queue_resilience_and_completion_broadcast(self):
        manager = JobManager()
        q = manager.subscribe()

        # Broadcast burst of messages
        for i in range(250):
            manager.broadcast("log", {"index": i})

        manager.broadcast("status", {"status": "completed"})
        manager.broadcast("completed", {"status": "completed"})

        # Subscriber must NOT be dropped from manager.subscribers
        self.assertIn(q, manager.subscribers)

        # Drain queue and verify completed event reached the queue
        events = []
        while not q.empty():
            events.append(q.get_nowait())

        completed_events = [e for e in events if "event: completed" in e or "completed" in e]
        self.assertTrue(len(completed_events) > 0)

    @patch("Backend.app.Crawler")
    def test_job_worker_broadcasts_completion_once_and_api_results_serves_data(self, mock_crawler_cls):
        mock_inst = MagicMock()
        mock_inst.skipped_reasons = []
        mock_inst.crawl.return_value = []
        mock_crawler_cls.return_value = mock_inst

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock index.json manifest
            sample_pages = [
                {"file": f"page_{i}.md", "url": f"https://example.com/{i}", "title": f"Page {i}", "depth": 0, "bytes": 1024}
                for i in range(150)
            ]
            manifest_path = Path(temp_dir) / "index.json"
            manifest_path.write_text(json.dumps(sample_pages), encoding="utf-8")

            client = app.test_client()
            resp = client.get(f"/api/results?output_dir={temp_dir}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["total_pages"], 150)
            self.assertTrue(data["has_manifest"])
            self.assertEqual(len(data["pages"]), 150)
            self.assertEqual(data["total_bytes"], 150 * 1024)

            # Test single clean broadcast on crawl run
            manager = JobManager()
            q = manager.subscribe()
            manager._run_crawler_worker(
                urls=["https://example.com"],
                output_format="md",
                depth=1,
                max_pages=1,
                same_domain=True,
                output_dir_str=temp_dir,
                dry_run=False,
            )
            events = []
            while not q.empty():
                events.append(q.get_nowait())
            completed_events = [e for e in events if "event: completed" in e]
            self.assertEqual(len(completed_events), 1)


class TestExportConversion(unittest.TestCase):
    def test_normalize_format_aliases(self):
        self.assertIsNone(normalize_format(""))
        self.assertIsNone(normalize_format("original"))
        self.assertEqual(normalize_format("markdown"), "md")
        self.assertEqual(normalize_format("text"), "txt")
        self.assertEqual(normalize_format("jsonl"), "jsonl")
        with self.assertRaises(ValueError):
            normalize_format("csv")

    def test_parse_json_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = OutputWriter(temp_dir, "json")
            writer.save_document(_document(), 1)
            writer.finalize()
            records = parse_saved_pages(Path(temp_dir))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["url"], "https://example.com/docs")
        self.assertIn("# Docs", records[0]["markdown"])
        self.assertEqual(records[0]["depth"], 1)

    def test_convert_json_to_markdown_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = OutputWriter(temp_dir, "json")
            writer.save_document(_document(), 0)
            writer.finalize()
            payload = build_results_zip(Path(temp_dir), "md")

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith(".md") for name in names))
            self.assertIn("index.json", names)
            markdown = archive.read(next(name for name in names if name.endswith(".md"))).decode("utf-8")
        self.assertIn("title: \"Docs\"", markdown)
        self.assertIn("# Docs", markdown)

    def test_convert_txt_to_jsonl_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = OutputWriter(temp_dir, "txt")
            writer.save_document(_document(), 2)
            writer.finalize()
            payload = build_results_zip(Path(temp_dir), "jsonl")

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertIn("pages.jsonl", archive.namelist())
            record = json.loads(archive.read("pages.jsonl").decode("utf-8").strip())
        self.assertEqual(record["url"], "https://example.com/docs")
        self.assertEqual(record["depth"], 2)
        self.assertIn("Hello world", record["text"])

    def test_original_zip_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = OutputWriter(temp_dir, "md")
            writer.save_document(_document(), 0)
            writer.finalize()
            payload = build_results_zip(Path(temp_dir), None)

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.endswith(".md") for name in names))
        self.assertIn("index.json", names)


class TestDownloadAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        writer = OutputWriter(self.temp_dir.name, "json")
        writer.save_document(_document(), 0)
        writer.finalize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_download_converts_to_requested_format(self):
        response = self.client.get(
            "/api/results/download",
            query_string={"output_dir": self.temp_dir.name, "format": "markdown"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("_md.zip", response.headers["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith(".md") for name in names))

    def test_download_rejects_unknown_format(self):
        response = self.client.get(
            "/api/results/download",
            query_string={"output_dir": self.temp_dir.name, "format": "csv"},
        )
        self.assertEqual(response.status_code, 400)

    def test_download_original_zip(self):
        response = self.client.get(
            "/api/results/download",
            query_string={"output_dir": self.temp_dir.name},
        )
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.endswith(".json") for name in names))


if __name__ == "__main__":
    unittest.main()
