"""Tests for Phase 6: Scalability, Queuing & Crawl Resilience (100% Local)."""

import json
import logging
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.app import JobManager, JobState, app
from Backend.cli import parse_args, run
from Backend.crawler import Crawler, Page
from Backend.fetcher import FetchError, FetchResult, Fetcher, NonHtmlContent, RobotsDisallowed
from Backend.retry import (
    CATEGORY_CIRCUIT_OPEN,
    CATEGORY_CONNECTION,
    CATEGORY_DNS,
    CATEGORY_HTTP_403,
    CATEGORY_HTTP_404,
    CATEGORY_HTTP_429,
    CATEGORY_HTTP_5XX,
    CATEGORY_NON_HTML,
    CATEGORY_PLAYWRIGHT_TIMEOUT,
    CATEGORY_ROBOTS,
    CATEGORY_TIMEOUT,
    CATEGORY_TLS,
    AdaptiveRateLimiter,
    DomainCircuitBreaker,
    RetryPolicy,
    classify_error,
)
from Backend.sitemap import parse_sitemap_entries
from Backend.state import CrawlStore, DeltaCache, content_hash
from Backend.writer import OutputWriter
from Backend.extractor import PageContent


class TestRetryAndResilience(unittest.TestCase):
    def test_classify_error_types(self):
        self.assertEqual(classify_error(socket.gaierror()), CATEGORY_DNS)
        self.assertEqual(classify_error(Exception("getaddrinfo failed")), CATEGORY_DNS)
        self.assertEqual(classify_error(Exception("certificate verify failed")), CATEGORY_TLS)
        self.assertEqual(classify_error(Exception("playwright timeout 30000ms")), CATEGORY_PLAYWRIGHT_TIMEOUT)
        self.assertEqual(classify_error(RobotsDisallowed("Disallowed")), CATEGORY_ROBOTS)
        self.assertEqual(classify_error(NonHtmlContent("image/png")), CATEGORY_NON_HTML)
        self.assertEqual(classify_error(None, status_code=403), CATEGORY_HTTP_403)
        self.assertEqual(classify_error(None, status_code=404), CATEGORY_HTTP_404)
        self.assertEqual(classify_error(None, status_code=429), CATEGORY_HTTP_429)
        self.assertEqual(classify_error(None, status_code=502), CATEGORY_HTTP_5XX)
        self.assertEqual(classify_error(Exception("Connection reset by peer")), CATEGORY_CONNECTION)
        self.assertEqual(classify_error(Exception("Operation timed out")), CATEGORY_TIMEOUT)

    def test_retry_policy(self):
        policy = RetryPolicy(max_attempts=3, base_delay=0.1, jitter=0.0)
        self.assertTrue(policy.should_retry(CATEGORY_HTTP_5XX, 1))
        self.assertTrue(policy.should_retry(CATEGORY_HTTP_5XX, 2))
        self.assertFalse(policy.should_retry(CATEGORY_HTTP_5XX, 3))
        # Non-retryable
        self.assertFalse(policy.should_retry(CATEGORY_HTTP_404, 1))
        self.assertFalse(policy.should_retry(CATEGORY_ROBOTS, 1))

        # Delays
        self.assertAlmostEqual(policy.next_delay(1), 0.1)
        self.assertAlmostEqual(policy.next_delay(2), 0.2)
        # Retry-After header respect
        self.assertEqual(policy.next_delay(1, retry_after=5.0), 5.0)

    def test_domain_circuit_breaker(self):
        breaker = DomainCircuitBreaker(failure_threshold=2, cooldown=0.1)
        domain = "example.com"
        self.assertTrue(breaker.allow(domain))
        self.assertEqual(breaker.state(domain), "closed")

        breaker.record_failure(domain)
        self.assertTrue(breaker.allow(domain))
        breaker.record_failure(domain)
        # Opened after 2 failures
        self.assertFalse(breaker.allow(domain))
        self.assertEqual(breaker.state(domain), "open")
        self.assertGreater(breaker.retry_after(domain), 0.0)

        # Wait for cooldown
        time.sleep(0.12)
        self.assertTrue(breaker.allow(domain))
        self.assertEqual(breaker.state(domain), "half_open")

        # Success closes circuit
        breaker.record_success(domain)
        self.assertEqual(breaker.state(domain), "closed")
        snapshot = breaker.snapshot()
        self.assertIn(domain, snapshot)
        self.assertEqual(snapshot[domain]["state"], "closed")

    def test_adaptive_rate_limiter(self):
        limiter = AdaptiveRateLimiter(base_delay=0.1, max_delay=1.0)
        domain = "api.example.com"
        self.assertAlmostEqual(limiter.delay_for(domain), 0.1)
        # Back off on throttle
        new_delay = limiter.record_throttle(domain)
        self.assertAlmostEqual(new_delay, 0.2)
        # Back off with retry-after
        limiter.record_throttle(domain, retry_after=0.5)
        self.assertAlmostEqual(limiter.delay_for(domain), 0.5)
        # Relax on success
        limiter.record_success(domain)
        self.assertLess(limiter.delay_for(domain), 0.5)


class TestCrawlStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "crawl_state.db"
        self.store = CrawlStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_job_crud(self):
        self.store.create_job("job1", output_dir="/tmp/out", config={"max_pages": 10})
        job = self.store.get_job("job1")
        self.assertIsNotNone(job)
        self.assertEqual(job["job_id"], "job1")
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["config"]["max_pages"], 10)

        self.store.update_job("job1", status="completed", stats={"saved": 5})
        updated = self.store.get_job("job1")
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["stats"]["saved"], 5)

        jobs = self.store.list_jobs()
        self.assertEqual(len(jobs), 1)

    def test_queue_and_atomic_claim(self):
        job_id = "test-job"
        self.store.create_job(job_id)
        inserted = self.store.enqueue_many(
            job_id,
            [
                ("https://example.com/1", 0, "example.com"),
                ("https://example.com/2", 1, "example.com"),
            ],
            max_total=5,
        )
        self.assertEqual(inserted, 2)
        # Duplicate enqueue is ignored
        dup = self.store.enqueue(job_id, "https://example.com/1")
        self.assertFalse(dup)

        stats = self.store.queue_stats(job_id)
        self.assertEqual(stats["pending"], 2)

        # Worker claims next item
        claimed1 = self.store.claim(job_id, worker_id="worker-A")
        self.assertIsNotNone(claimed1)
        self.assertEqual(claimed1["url"], "https://example.com/1")
        self.assertEqual(claimed1["claimed_by"], "worker-A")

        # Worker B claims next
        claimed2 = self.store.claim(job_id, worker_id="worker-B")
        self.assertEqual(claimed2["url"], "https://example.com/2")

        # Nothing left
        self.assertIsNone(self.store.claim(job_id, worker_id="worker-C"))

        # Complete claimed1
        self.store.complete(job_id, claimed1["url"], hash_value="abc123hash", status="done")
        self.assertTrue(self.store.is_visited(job_id, claimed1["url"]))

        # Mark skipped claimed2
        self.store.mark_skipped(job_id, claimed2["url"], reason="filtered")

        stats2 = self.store.queue_stats(job_id)
        self.assertEqual(stats2["done"], 1)
        self.assertEqual(stats2["skipped"], 1)
        self.assertEqual(stats2["pending"], 0)

    def test_failure_retry_and_dlq(self):
        job_id = "fail-job"
        url = "https://example.com/error"
        self.store.create_job(job_id)
        self.store.enqueue(job_id, url)
        claimed = self.store.claim(job_id)

        # Attempt 1: retryable
        res1 = self.store.fail(job_id, url, category=CATEGORY_TIMEOUT, retryable=True, delay_seconds=0.01)
        self.assertTrue(res1["retry"])
        self.assertEqual(res1["attempts"], 1)
        self.assertEqual(len(self.store.failures(job_id)), 0)

        # Re-claim and fail with retryable=False (moves to DLQ)
        claimed2 = self.store.claim(job_id)
        res2 = self.store.fail(job_id, url, category=CATEGORY_HTTP_404, retryable=False)
        self.assertFalse(res2["retry"])

        failures = self.store.failures(job_id)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["url"], url)
        self.assertEqual(failures[0]["error_category"], CATEGORY_HTTP_404)

        # Requeue failed
        requeued = self.store.requeue_failed(job_id)
        self.assertEqual(requeued, 1)
        self.assertEqual(len(self.store.failures(job_id)), 0)
        reclaimed = self.store.claim(job_id)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["url"], url)

    def test_lease_expiration_recovery(self):
        job_id = "lease-job"
        url = "https://example.com/stale"
        self.store.create_job(job_id)
        self.store.enqueue(job_id, url)
        # Claim with very short lease
        self.store.claim(job_id, worker_id="crashed-worker", lease_seconds=0.01)
        time.sleep(0.05)
        # Next claim should auto-reclaim the expired lease (leases older than 0.01s)
        reclaimed = self.store.claim(job_id, worker_id="active-worker", lease_seconds=0.01)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["claimed_by"], "active-worker")


class TestDeltaCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "crawl_state.db"
        self.cache = DeltaCache(self.db_path)

    def tearDown(self):
        self.cache.close()
        self.temp_dir.cleanup()

    def test_hash_and_cache(self):
        text = "Hello world content"
        h = content_hash(text)
        self.assertEqual(len(h), 64)

        url = "https://example.com/page"
        self.cache.record(
            url,
            hash_value=h,
            etag='"etag-123"',
            last_modified="Wed, 21 Oct 2026 07:28:00 GMT",
            links=["https://example.com/sub"],
        )

        self.assertTrue(self.cache.has(url))
        self.assertTrue(self.cache.is_unchanged(url, h))
        self.assertFalse(self.cache.is_unchanged(url, "different-hash"))

        headers = self.cache.conditional_headers(url)
        self.assertEqual(headers.get("If-None-Match"), '"etag-123"')
        self.assertEqual(headers.get("If-Modified-Since"), "Wed, 21 Oct 2026 07:28:00 GMT")

        cached = self.cache.get(url)
        self.assertEqual(cached["links"], ["https://example.com/sub"])

    def test_sitemap_lastmod_skipping(self):
        url = "https://example.com/article"
        self.cache.record(
            url,
            hash_value="abc",
            sitemap_lastmod="2026-11-10T12:00:00Z",
        )
        # Incoming lastmod is older -> should skip
        self.assertTrue(self.cache.should_skip_before_fetch(url, "2026-11-09T10:00:00Z"))
        # Incoming lastmod is same -> should skip
        self.assertTrue(self.cache.should_skip_before_fetch(url, "2026-11-10T12:00:00Z"))
        # Incoming lastmod is newer -> should NOT skip
        self.assertFalse(self.cache.should_skip_before_fetch(url, "2026-11-11T15:00:00Z"))


class TestIncrementalOutputWriter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_incremental_writer_updates_manifest(self):
        doc1 = PageContent(
            url="https://example.com/page1",
            title="Version 1",
            text="Initial text",
            markdown="Initial text",
        )
        writer = OutputWriter(str(self.output_dir), output_format="md", incremental=True)
        file1 = writer.save_document(doc1, depth=0)
        writer.finalize()

        self.assertTrue((self.output_dir / file1).exists())
        self.assertEqual(len(writer.manifest), 1)

        # Second write with incremental=True updates existing file name and manifest entry
        doc2 = PageContent(
            url="https://example.com/page1",
            title="Version 2",
            text="Updated text",
            markdown="Updated text",
        )
        writer2 = OutputWriter(str(self.output_dir), output_format="md", incremental=True)
        file2 = writer2.save_document(doc2, depth=0)
        writer2.finalize()

        self.assertEqual(file1, file2)
        self.assertEqual(len(writer2.manifest), 1)
        self.assertEqual(writer2.manifest[0]["title"], "Version 2")


class TestSitemapEntries(unittest.TestCase):
    def test_parse_sitemap_entries_with_lastmod(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/page-1</loc>
            <lastmod>2026-11-12T10:00:00Z</lastmod>
          </url>
          <url>
            <loc>https://example.com/page-2</loc>
          </url>
        </urlset>"""
        entries, sub_sitemaps = parse_sitemap_entries(xml_content)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["url"], "https://example.com/page-1")
        self.assertEqual(entries[0]["lastmod"], "2026-11-12T10:00:00Z")
        self.assertEqual(entries[1]["url"], "https://example.com/page-2")
        self.assertEqual(entries[1]["lastmod"], "")
        self.assertEqual(sub_sitemaps, [])


class TestCrawlerPhase6(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_db = Path(self.temp_dir.name) / "crawl_state.db"
        self.store = CrawlStore(self.state_db)
        self.delta_cache = DeltaCache(self.state_db)
        self.logger = logging.getLogger("test_crawler_phase6")

    def tearDown(self):
        self.delta_cache.close()
        self.store.close()
        self.temp_dir.cleanup()

    def test_crawler_incremental_and_checkpoint(self):
        job_id = "test-job-c1"
        mock_fetcher = MagicMock()

        # Seed page
        mock_fetcher.fetch.side_effect = [
            FetchResult(
                requested_url="https://example.com/",
                final_url="https://example.com/",
                html="<html><body><a href='/sub'>Sub</a></body></html>",
                status_code=200,
                content_type="text/html",
                etag='"etag-v1"',
                content_hash="hash-1",
            ),
            FetchResult(
                requested_url="https://example.com/sub",
                final_url="https://example.com/sub",
                html="<html><body>Subpage content</body></html>",
                status_code=200,
                content_type="text/html",
                content_hash="hash-sub",
            ),
        ]

        crawler = Crawler(
            max_depth=1,
            max_pages=5,
            same_domain=True,
            logger=self.logger,
            fetcher=mock_fetcher,
            store=self.store,
            delta=self.delta_cache,
            job_id=job_id,
            concurrency=1,
        )

        pages = list(crawler.crawl(["https://example.com/"]))
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].url, "https://example.com/")
        self.assertEqual(pages[1].url, "https://example.com/sub")

        # Delta cache has records
        self.assertTrue(self.delta_cache.has("https://example.com/"))
        self.assertTrue(self.delta_cache.has("https://example.com/sub"))

        # Second crawl: 304 Not Modified
        mock_fetcher.fetch.side_effect = [
            FetchResult(
                requested_url="https://example.com/",
                final_url="https://example.com/",
                html="",
                status_code=304,
                content_type="text/html",
                not_modified=True,
                etag='"etag-v1"',
                content_hash="hash-1",
            ),
            # Subpage unchanged content hash
            FetchResult(
                requested_url="https://example.com/sub",
                final_url="https://example.com/sub",
                html="<html><body>Subpage content</body></html>",
                status_code=200,
                content_type="text/html",
                content_hash="hash-sub",
            ),
        ]

        crawler2 = Crawler(
            max_depth=1,
            max_pages=5,
            same_domain=True,
            logger=self.logger,
            fetcher=mock_fetcher,
            store=self.store,
            delta=self.delta_cache,
            job_id="test-job-c2",
            concurrency=1,
        )

        pages2 = list(crawler2.crawl(["https://example.com/"]))
        self.assertEqual(len(pages2), 2)
        self.assertTrue(pages2[0].unchanged)
        self.assertTrue(pages2[1].unchanged)

    def test_crawler_dlq_on_repeated_failure(self):
        job_id = "test-job-dlq"
        mock_fetcher = MagicMock()
        mock_fetcher.fetch.side_effect = FetchError("Server down", status_code=500, error_type=CATEGORY_HTTP_5XX)

        failures_captured = []
        crawler = Crawler(
            max_depth=0,
            max_pages=1,
            same_domain=True,
            logger=self.logger,
            fetcher=mock_fetcher,
            store=self.store,
            job_id=job_id,
            max_retries=1,
            concurrency=1,
            on_failure=lambda f: failures_captured.append(f),
        )

        pages = list(crawler.crawl(["https://example.com/fail"]))
        self.assertEqual(len(pages), 0)
        dlq = self.store.failures(job_id)
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0]["error_category"], CATEGORY_HTTP_5XX)
        self.assertEqual(len(failures_captured), 1)

    def test_crawler_concurrent_persistent(self):
        job_id = "test-job-concurrent"
        mock_fetcher = MagicMock()
        mock_fetcher.fetch.side_effect = [
            FetchResult(
                requested_url="https://example.com/a",
                final_url="https://example.com/a",
                html="<html><body>Page A</body></html>",
                status_code=200,
                content_type="text/html",
                content_hash="h-a",
            ),
            FetchResult(
                requested_url="https://example.com/b",
                final_url="https://example.com/b",
                html="<html><body>Page B</body></html>",
                status_code=200,
                content_type="text/html",
                content_hash="h-b",
            ),
        ]
        crawler = Crawler(
            max_depth=0,
            max_pages=2,
            same_domain=True,
            logger=self.logger,
            fetcher=mock_fetcher,
            store=self.store,
            job_id=job_id,
            concurrency=2,
        )
        pages = list(crawler.crawl(["https://example.com/a", "https://example.com/b"]))
        self.assertEqual(len(pages), 2)
        urls = {p.url for p in pages}
        self.assertEqual(urls, {"https://example.com/a", "https://example.com/b"})
        stats = self.store.queue_stats(job_id)
        self.assertEqual(stats["done"], 2)

    def test_crawler_resume_and_sitemap_lastmod_skip(self):
        job_id = "test-job-resume"
        # Seed cache with a known URL and lastmod
        self.delta_cache.record(
            "https://example.com/cached",
            hash_value="cached-hash-123",
            sitemap_lastmod="2026-11-12T10:00:00Z",
        )

        mock_fetcher = MagicMock()
        crawler = Crawler(
            max_depth=0,
            max_pages=1,
            same_domain=True,
            logger=self.logger,
            fetcher=mock_fetcher,
            store=self.store,
            delta=self.delta_cache,
            job_id=job_id,
            concurrency=1,
            resume=True,
        )
        # Prepopulate sitemap_lastmods matching or older than cached
        crawler._sitemap_lastmods["https://example.com/cached"] = "2026-11-10T10:00:00Z"
        pages = list(crawler.crawl(["https://example.com/cached"]))
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].unchanged)
        # Fetch was skipped completely before making any HTTP request!
        mock_fetcher.fetch.assert_not_called()


class TestApiPhase6Endpoints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_api_jobs_and_failures(self):
        # Create a store and record a job with DLQ failure
        state_db = JobManager.state_path_for(str(self.output_dir))
        store = CrawlStore(state_db)
        store.create_job("job-abc", output_dir=str(self.output_dir), config={"urls": ["https://example.com"]})
        store.enqueue("job-abc", "https://example.com/bad")
        store.claim("job-abc")
        store.fail("job-abc", "https://example.com/bad", category=CATEGORY_HTTP_404, retryable=False, message="Not Found")
        store.close()

        # GET /api/jobs
        resp = self.client.get(f"/api/jobs?output_dir={self.output_dir}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["jobs"]), 1)
        self.assertEqual(data["jobs"][0]["job_id"], "job-abc")

        # GET /api/jobs/<job_id>
        resp_detail = self.client.get(f"/api/jobs/job-abc?output_dir={self.output_dir}")
        self.assertEqual(resp_detail.status_code, 200)
        detail = resp_detail.get_json()
        self.assertEqual(len(detail["failures"]), 1)

        # GET /api/scrape/failures
        resp_failures = self.client.get(f"/api/scrape/failures?job_id=job-abc&output_dir={self.output_dir}")
        self.assertEqual(resp_failures.status_code, 200)
        failures_data = resp_failures.get_json()
        self.assertEqual(failures_data["total_failures"], 1)
        self.assertEqual(failures_data["failures"][0]["url"], "https://example.com/bad")

        # GET /api/scrape/delta-stats
        resp_delta = self.client.get(f"/api/scrape/delta-stats?output_dir={self.output_dir}")
        self.assertEqual(resp_delta.status_code, 200)
        self.assertIn("cached_urls", resp_delta.get_json())

    def test_api_resume_and_retry_failed_endpoints(self):
        state_db = JobManager.state_path_for(str(self.output_dir))
        store = CrawlStore(state_db)
        store.create_job(
            "job-retry",
            output_dir=str(self.output_dir),
            config={"urls": ["https://example.com/one", "https://example.com/two"], "depth": 0, "max_pages": 5},
        )
        store.enqueue("job-retry", "https://example.com/one")
        store.claim("job-retry")
        store.fail("job-retry", "https://example.com/one", category=CATEGORY_TIMEOUT, retryable=False, message="Timeout")
        store.close()

        # Retry failed through API with mock crawler run
        with patch.object(JobManager, "start_crawl", return_value=(True, "Crawl job started.")) as mock_start:
            resp = self.client.post(
                "/api/scrape/retry-failed",
                json={"job_id": "job-retry", "output_dir": str(self.output_dir)},
            )
            self.assertEqual(resp.status_code, 200)
            mock_start.assert_called_once()
            self.assertTrue(mock_start.call_args[1].get("requeue_failed"))

        # Resume job through /api/jobs/<job_id>/resume
        with patch.object(JobManager, "start_crawl", return_value=(True, "Crawl job started.")) as mock_start2:
            resp_res = self.client.post(
                "/api/jobs/job-retry/resume",
                json={"output_dir": str(self.output_dir)},
            )
            self.assertEqual(resp_res.status_code, 200)
            mock_start2.assert_called_once()

    def test_api_start_with_dlq_toggle(self):
        with patch.object(JobManager, "start_crawl", return_value=(True, "Crawl job started.")) as mock_start:
            resp = self.client.post(
                "/api/scrape/start",
                json={"urls": ["https://example.com"], "dlq": True},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(mock_start.call_args[1].get("dlq"))

        with patch.object(JobManager, "start_crawl", return_value=(True, "Crawl job started.")) as mock_start_off:
            resp = self.client.post(
                "/api/scrape/start",
                json={"urls": ["https://example.com"], "dlq": False},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(mock_start_off.call_args[1].get("dlq"))


class TestCliPhase6Options(unittest.TestCase):
    def test_cli_parser_phase6_flags(self):
        args = parse_args([
            "--url", "https://example.com",
            "--incremental",
            "--checkpoint",
            "--max-retries", "3",
            "--adaptive-rate-limit",
            "--dlq",
            "--resume", "job-1234",
        ])
        self.assertTrue(args.incremental)
        self.assertTrue(args.checkpoint)
        self.assertEqual(args.max_retries, 3)
        self.assertTrue(args.adaptive_rate_limit)
        self.assertTrue(args.dlq)
        self.assertEqual(args.resume, "job-1234")

    def test_cli_list_failures(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            db_path = out_dir / ".scraper" / "crawl_state.db"
            store = CrawlStore(db_path)
            store.create_job("job-list", output_dir=str(out_dir))
            store.enqueue("job-list", "https://example.com/fail")
            store.claim("job-list")
            store.fail("job-list", "https://example.com/fail", category=CATEGORY_HTTP_5XX, retryable=False, message="500 Internal Error")
            store.close()

            args = parse_args([
                "--list-failures", "job-list",
                "--output-dir", str(out_dir),
                "--json",
            ])
            with patch("sys.stdout") as mock_stdout:
                ret = run(args)
                self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
