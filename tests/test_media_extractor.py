"""Unit tests for the Media Extractor feature."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.cli import build_parser, parse_args
from Backend.extractor import PageContent, extract_structured
from Backend.media import (
    ALL_MEDIA_EXTENSIONS,
    MEDIA_CATEGORIES,
    MediaCollector,
    MediaItem,
    classify_media_url,
    download_media_file,
    extract_filename_and_ext,
    extract_media_from_html,
    normalize_media_type,
    parse_media_types,
    sanitize_filename,
)
from Backend.scraper import scrape_url
from Backend.writer import OutputWriter


class TestMediaExtractor(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_media_classification_and_normalization(self) -> None:
        self.assertEqual(normalize_media_type("images"), "image")
        self.assertEqual(normalize_media_type("PDF"), "pdf")
        self.assertEqual(normalize_media_type("documents"), "doc")
        self.assertEqual(normalize_media_type("presentation"), "ppt")
        self.assertEqual(normalize_media_type("videos"), "video")
        self.assertIsNone(normalize_media_type("unknown_type"))

        parsed = parse_media_types("image,pdf,video")
        self.assertEqual(parsed, {"image", "pdf", "video"})

        # Classify by URL extension
        cat, ext = classify_media_url("https://example.com/assets/annual-report.pdf?v=2")
        self.assertEqual(cat, "pdf")
        self.assertEqual(ext, ".pdf")

        cat, ext = classify_media_url("https://example.com/images/banner.webp")
        self.assertEqual(cat, "image")
        self.assertEqual(ext, ".webp")

        cat, ext = classify_media_url("https://example.com/files/spec.docx")
        self.assertEqual(cat, "doc")
        self.assertEqual(ext, ".docx")

        cat, ext = classify_media_url("https://example.com/slides/deck.pptx")
        self.assertEqual(cat, "ppt")
        self.assertEqual(ext, ".pptx")

        cat, ext = classify_media_url("https://example.com/media/demo.mp4")
        self.assertEqual(cat, "video")
        self.assertEqual(ext, ".mp4")

        # Classify with tag hint when URL has no extension
        cat, ext = classify_media_url("https://example.com/avatar?uid=123", tag_hint="img")
        self.assertEqual(cat, "image")

        cat, ext = classify_media_url("https://example.com/stream?id=99", tag_hint="video")
        self.assertEqual(cat, "video")

    def test_sanitize_filename(self) -> None:
        self.assertEqual(sanitize_filename("bad/name:with*chars?.pdf"), "bad_name_with_chars_.pdf")
        self.assertEqual(sanitize_filename(""), "asset")

        filename, ext = extract_filename_and_ext("https://example.com/docs/annual_review.pdf?dl=1")
        self.assertEqual(filename, "annual_review.pdf")
        self.assertEqual(ext, ".pdf")

    def test_extract_media_from_html_all_types(self) -> None:
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <header>
                <img src="/images/logo.png" alt="Company Logo" />
                <picture>
                    <source srcset="/images/hero-1x.jpg 1x, /images/hero-2x.jpg 2x" />
                    <img src="/images/hero-fallback.jpg" alt="Hero Banner" />
                </picture>
            </header>
            <main>
                <p>Welcome to our downloads page:</p>
                <ul>
                    <li><a href="/downloads/whitepaper.pdf">Download Whitepaper (PDF)</a></li>
                    <li><a href="/downloads/manual.docx">User Manual (DOCX)</a></li>
                    <li><a href="/downloads/slides.pptx">Pitch Deck (PPTX)</a></li>
                    <li><a href="/downloads/clip.mp4">Product Video (MP4)</a></li>
                </ul>
                <video src="/media/promo.webm" poster="/media/poster.png">
                    <source src="/media/promo.mp4" type="video/mp4" />
                </video>
            </main>
        </body>
        </html>
        """
        page_url = "https://example.com/products/software"
        items = extract_media_from_html(sample_html, page_url)

        # Check all categories are detected
        types_found = {item.media_type for item in items}
        self.assertIn("image", types_found)
        self.assertIn("pdf", types_found)
        self.assertIn("doc", types_found)
        self.assertIn("ppt", types_found)
        self.assertIn("video", types_found)

        # Verify absolute URL resolution
        pdf_items = [i for i in items if i.media_type == "pdf"]
        self.assertEqual(len(pdf_items), 1)
        self.assertEqual(pdf_items[0].media_url, "https://example.com/downloads/whitepaper.pdf")
        self.assertEqual(pdf_items[0].page_url, page_url)
        self.assertEqual(pdf_items[0].filename, "whitepaper.pdf")

        # Verify filtering by allowed types
        only_docs = extract_media_from_html(sample_html, page_url, allowed_types={"doc", "ppt"})
        self.assertEqual({i.media_type for i in only_docs}, {"doc", "ppt"})

    def test_media_collector_and_manifest_generation(self) -> None:
        collector = MediaCollector(allowed_types={"pdf", "image"})
        page1_html = '<a href="/doc1.pdf">Doc 1</a><img src="/img1.png" alt="Img 1">'
        page2_html = '<a href="/doc1.pdf">Duplicate Doc</a><a href="/doc2.pdf">Doc 2</a>'

        new1 = collector.add_page_media("https://example.com/p1", page1_html)
        self.assertEqual(len(new1), 2)

        # On page 2, /doc1.pdf is deduplicated across pages
        new2 = collector.add_page_media("https://example.com/p2", page2_html)
        self.assertEqual(len(new2), 1)
        self.assertEqual(new2[0].media_url, "https://example.com/doc2.pdf")

        json_path, csv_path = collector.write_manifests(self.output_dir)
        self.assertTrue(json_path.exists())
        self.assertTrue(csv_path.exists())

        manifest_data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest_data), 3)
        self.assertEqual(manifest_data[0]["page_url"], "https://example.com/p1")
        self.assertIn("media_type", manifest_data[0])
        self.assertIn("media_url", manifest_data[0])

        summary = collector.get_summary()
        self.assertEqual(summary["total_media"], 3)
        self.assertEqual(summary["by_category"]["pdf"], 2)
        self.assertEqual(summary["by_category"]["image"], 1)

    def test_download_media_file_mock(self) -> None:
        item = MediaItem(
            page_url="https://example.com/docs",
            media_type="pdf",
            media_url="https://example.com/files/spec.pdf",
            filename="spec.pdf",
        )

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.iter_content.return_value = [b"%PDF-1.4 fake content chunk 1", b" chunk 2"]
        fake_response.__enter__.return_value = fake_response
        fake_response.__exit__.return_value = None

        fake_session = MagicMock()
        fake_session.get.return_value = fake_response

        ok = download_media_file(item, self.output_dir, session=fake_session)
        self.assertTrue(ok)
        self.assertEqual(item.download_status, "downloaded")
        self.assertEqual(item.downloaded_path, "media/pdf/spec.pdf")
        self.assertGreater(item.size_bytes, 0)

        saved_file = self.output_dir / "media" / "pdf" / "spec.pdf"
        self.assertTrue(saved_file.is_file())
        self.assertEqual(saved_file.read_bytes(), b"%PDF-1.4 fake content chunk 1 chunk 2")

    def test_output_writer_media_only_mode(self) -> None:
        writer = OutputWriter(str(self.output_dir), output_format="md", media_only=True)
        doc = PageContent(
            url="https://example.com/article",
            title="Article",
            text="Article text",
            markdown="# Article\n\nArticle text",
        )
        saved_name = writer.save_document(doc, depth=0)
        writer.finalize()

        # In media-only mode, regular page text/markdown file is NOT written
        self.assertEqual(saved_name, "")
        md_files = list(self.output_dir.glob("*.md"))
        self.assertEqual(len(md_files), 0)

        # index.json is written noting media-only run
        index_file = self.output_dir / "index.json"
        self.assertTrue(index_file.exists())
        index_data = json.loads(index_file.read_text(encoding="utf-8"))
        self.assertEqual(index_data[0]["mode"], "media_only")

    def test_extract_structured_with_media(self) -> None:
        html = '<h1>Header</h1><p>Text</p><a href="/file.pdf">PDF</a><img src="/photo.jpg" alt="Photo">'
        doc = extract_structured(html, url="https://example.com/test", extract_media=True)
        self.assertEqual(len(doc.media), 2)
        urls = {m["media_url"] for m in doc.media}
        self.assertIn("https://example.com/file.pdf", urls)
        self.assertIn("https://example.com/photo.jpg", urls)

    def test_cli_parser_media_options(self) -> None:
        parser = build_parser()
        args = parse_args(["--url", "https://example.com", "--extract-media", "--download-media", "--media-types", "pdf,video"])
        self.assertTrue(args.extract_media)
        self.assertTrue(args.download_media)
        self.assertEqual(args.media_types, "pdf,video")

        args_only = parse_args(["--url", "https://example.com", "--media-only"])
        self.assertTrue(args_only.media_only)

    def test_api_media_endpoint(self) -> None:
        from Backend.app import app
        client = app.test_client()

        # Write sample manifest
        manifest_data = [
            {
                "page_url": "https://example.com/page",
                "media_type": "pdf",
                "media_url": "https://example.com/doc.pdf",
                "filename": "doc.pdf",
                "download_status": "discovered",
            }
        ]
        (self.output_dir / "media_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        response = client.get(f"/api/media?output_dir={self.output_dir}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total_media"], 1)
        self.assertEqual(data["media"][0]["media_type"], "pdf")

    def test_progressive_manifest_flushing(self) -> None:
        """Verify manifests are flushed to disk on every addition so nothing is lost if stopped."""
        collector = MediaCollector(allowed_types={"image", "pdf"})
        page1_html = '<a href="/file1.pdf">PDF 1</a>'
        collector.add_page_media("https://example.com/p1", page1_html, output_dir=self.output_dir)

        json_path = self.output_dir / "media_manifest.json"
        csv_path = self.output_dir / "media_manifest.csv"
        self.assertTrue(json_path.exists())
        self.assertTrue(csv_path.exists())

        data1 = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data1), 1)
        self.assertEqual(data1[0]["filename"], "file1.pdf")

        # Second page addition immediately updates manifest files on disk
        page2_html = '<img src="/pic.png" alt="Pic">'
        collector.add_page_media("https://example.com/p2", page2_html, output_dir=self.output_dir)

        data2 = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data2), 2)

    def test_output_writer_progressive_manifest_flushing(self) -> None:
        """Verify OutputWriter flushes index.json after saving each page."""
        writer = OutputWriter(str(self.output_dir), output_format="txt")
        doc1 = PageContent(url="https://example.com/page1", title="Page 1", text="Hello 1")
        writer.save_document(doc1, depth=0)

        index_file = self.output_dir / "index.json"
        self.assertTrue(index_file.exists())
        records = json.loads(index_file.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["url"], "https://example.com/page1")

    def test_job_manager_stop_and_reset(self) -> None:
        """Verify job manager properly transitions to stopped and reset."""
        from Backend.app import job_manager
        with job_manager.lock:
            job_manager.state.status = "running"
        
        ok, msg = job_manager.stop_crawl()
        self.assertTrue(ok)
        self.assertEqual(job_manager.state.status, "stopping")
        self.assertTrue(job_manager.stop_event.is_set())

        # Resetting while stopping clears state and stops
        job_manager.reset()
        self.assertEqual(job_manager.state.status, "idle")

    @patch("Backend.app.scrape_url")
    def test_api_scrape_with_extract_media(self, mock_scrape_url: MagicMock) -> None:
        from Backend.app import app
        mock_doc = PageContent(
            url="https://example.com/test",
            title="Test",
            text="Body",
            markdown="# Test",
            media=[{"page_url": "https://example.com/test", "media_type": "pdf", "media_url": "https://example.com/f.pdf"}],
        )
        mock_scrape_url.return_value = mock_doc

        client = app.test_client()
        resp = client.post("/api/scrape", json={"url": "https://example.com/test", "format": "json", "extract_media": True})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("media", data)
        self.assertEqual(len(data["media"]), 1)
        self.assertEqual(data["media"][0]["media_type"], "pdf")

    def test_download_media_batch_and_api_endpoint(self) -> None:
        from Backend.app import app
        from Backend.media import download_media_batch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        items = [
            MediaItem(page_url="https://example.com", media_type="image", media_url="https://example.com/img1.png"),
            MediaItem(page_url="https://example.com", media_type="image", media_url="https://example.com/img2.png"),
        ]

        dl, fl = download_media_batch(items, self.output_dir, session=mock_session)
        self.assertEqual(dl, 2)
        self.assertEqual(fl, 0)
        self.assertTrue((self.output_dir / "media" / "image" / "img1.png").is_file())
        self.assertTrue((self.output_dir / "media" / "image" / "img2.png").is_file())

        # Test POST /api/media/download
        (self.output_dir / "media_manifest.json").write_text(
            json.dumps([{"page_url": "https://example.com", "media_type": "image", "media_url": "https://example.com/img3.png"}]),
            encoding="utf-8",
        )
        with patch("Backend.media.download_media_file") as mock_dl:
            def _fake_dl(item, out, session=None):
                item.download_status = "downloaded"
                item.downloaded_path = f"media/{item.media_type}/{item.filename}"
                return True
            mock_dl.side_effect = _fake_dl

            client = app.test_client()
            resp = client.post("/api/media/download", json={"output_dir": str(self.output_dir)})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["downloaded"], 1)

    def test_api_media_clear(self) -> None:
        from Backend.app import app, job_manager

        # Set up media files and manifests on disk
        media_img_dir = self.output_dir / "media" / "image"
        media_img_dir.mkdir(parents=True, exist_ok=True)
        (media_img_dir / "pic.png").write_bytes(b"image data")
        (self.output_dir / "media_manifest.json").write_text("[]", encoding="utf-8")
        (self.output_dir / "media_manifest.csv").write_text("", encoding="utf-8")

        with job_manager.lock:
            job_manager.state.recent_media = [{"media_url": "https://example.com/pic.png"}]
            job_manager.state.media_extracted = 1
            job_manager.state.media_downloaded = 1

        client = app.test_client()
        resp = client.post("/api/media/clear", json={"output_dir": str(self.output_dir), "delete_files": True})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "cleared")
        self.assertGreaterEqual(data["deleted_files"], 1)

        # Verify disk files removed
        self.assertFalse((media_img_dir / "pic.png").exists())
        self.assertFalse((self.output_dir / "media").exists())
        self.assertFalse((self.output_dir / "media_manifest.json").exists())

        # Verify in-memory state cleared
        self.assertEqual(len(job_manager.state.recent_media), 0)
        self.assertEqual(job_manager.state.media_extracted, 0)
        self.assertEqual(job_manager.state.media_downloaded, 0)


if __name__ == "__main__":
    unittest.main()
