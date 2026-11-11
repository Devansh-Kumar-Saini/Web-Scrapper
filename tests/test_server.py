"""Integration tests for web server endpoints, health checks, and WSGI entry points."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from Backend.app import app, _is_container
from Backend.cli import parse_args


class TestServerEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_health_check_returns_ok(self) -> None:
        """The /api/health endpoint must return HTTP 200 with status ok (used by Docker HEALTHCHECK)."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_ui_index_served(self) -> None:
        """The root URL / must serve the web UI HTML."""
        with self.client.get("/") as response:
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn("Web Scraper", text)
            self.assertIn("<html", text.lower())

    def test_static_assets_served(self) -> None:
        """Core CSS and JS files must be reachable from the static folder."""
        with self.client.get("/styles.css") as css_resp:
            self.assertEqual(css_resp.status_code, 200)
            self.assertTrue(len(css_resp.get_data()) > 0)

        with self.client.get("/app.js") as js_resp:
            self.assertEqual(js_resp.status_code, 200)
            self.assertTrue(len(js_resp.get_data()) > 0)

    @patch.dict("os.environ", {"SCRAPER_CONTAINER": "1"})
    def test_pick_folder_container_mode(self) -> None:
        """When running in a container, pick-folder must explain that Docker mounts ./output."""
        self.assertTrue(_is_container())
        response = self.client.post("/api/system/pick-folder")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("container"))
        self.assertTrue(data.get("is_cloud"))
        self.assertEqual(data.get("path"), "./output")
        self.assertIn("Docker", data.get("message", ""))

    def test_wsgi_app_callable(self) -> None:
        """Backend.app.app must be a callable WSGI application for Gunicorn."""
        self.assertTrue(callable(app))
        self.assertTrue(hasattr(app, "wsgi_app"))

    def test_cli_parsing_for_ui_and_scraper(self) -> None:
        """CLI arguments for launching the UI or running scraping jobs must parse reliably."""
        ui_args = parse_args(["--ui", "--port", "8080", "--host", "127.0.0.1"])
        self.assertTrue(ui_args.ui)
        self.assertEqual(ui_args.port, 8080)
        self.assertEqual(ui_args.host, "127.0.0.1")

        cli_args = parse_args(["--url", "https://example.com", "--dry-run", "--format", "md"])
        self.assertFalse(cli_args.ui)
        self.assertEqual(cli_args.url, ["https://example.com"])
        self.assertTrue(cli_args.dry_run)
        self.assertEqual(cli_args.format, "md")


if __name__ == "__main__":
    unittest.main()
