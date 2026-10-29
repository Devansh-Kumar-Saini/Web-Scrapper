"""Tests for native folder picker and custom output directory support."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.app import PROJECT_ROOT, _pick_folder_native, _resolve_output_dir, app
from Backend.writer import OutputWriter


class TestOutputDirectory(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_resolve_output_dir_relative(self):
        resolved = _resolve_output_dir("./output")
        expected = (PROJECT_ROOT / "output").resolve()
        self.assertEqual(resolved, expected)

    def test_resolve_output_dir_empty(self):
        resolved = _resolve_output_dir("")
        expected = (PROJECT_ROOT / "output").resolve()
        self.assertEqual(resolved, expected)

    def test_resolve_output_dir_absolute(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolved = _resolve_output_dir(tmp_dir)
            self.assertEqual(resolved, Path(tmp_dir).resolve())

    def test_resolve_output_dir_tilde(self):
        resolved = _resolve_output_dir("~/test_folder")
        expected = (Path.home() / "test_folder").resolve()
        self.assertEqual(resolved, expected)

    @patch("Backend.app.sys.platform", "darwin")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_darwin_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/Users/test/OutputFolder/\n", stderr="")
        canceled, path, error = _pick_folder_native()
        self.assertFalse(canceled)
        self.assertEqual(path, "/Users/test/OutputFolder")
        self.assertEqual(error, "")

    @patch("Backend.app.sys.platform", "darwin")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_darwin_canceled(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="execution error: User canceled. (-128)")
        canceled, path, error = _pick_folder_native()
        self.assertTrue(canceled)
        self.assertEqual(path, "")
        self.assertEqual(error, "")

    @patch("Backend.app.sys.platform", "darwin")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_darwin_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="osascript: unexpected error")
        canceled, path, error = _pick_folder_native()
        self.assertFalse(canceled)
        self.assertEqual(path, "")
        self.assertIn("unexpected error", error)

    @patch("Backend.app.sys.platform", "win32")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_windows_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="C:\\Scrapes\n", stderr="")
        canceled, path, error = _pick_folder_native()
        self.assertFalse(canceled)
        self.assertEqual(path, "C:\\Scrapes")
        self.assertEqual(error, "")

    @patch("Backend.app.sys.platform", "win32")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_windows_cancel(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        canceled, path, error = _pick_folder_native()
        self.assertTrue(canceled)
        self.assertEqual(path, "")

    @patch("Backend.app.sys.platform", "linux")
    @patch("Backend.app.subprocess.run")
    def test_pick_folder_linux_zenity(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/home/user/scrapes\n", stderr="")
        canceled, path, error = _pick_folder_native()
        self.assertFalse(canceled)
        self.assertEqual(path, "/home/user/scrapes")

    @patch("Backend.app.sys.platform", "darwin")
    @patch("Backend.app.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=300))
    def test_pick_folder_timeout(self, mock_run):
        canceled, path, error = _pick_folder_native()
        self.assertTrue(canceled)
        self.assertEqual(path, "")
        self.assertEqual(error, "")

    @patch("Backend.app._pick_folder_native")
    def test_api_pick_folder_canceled(self, mock_picker):
        mock_picker.return_value = (True, "", "")
        resp = self.client.post("/api/system/pick-folder")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("canceled"))

    @patch("Backend.app._pick_folder_native")
    def test_api_pick_folder_success(self, mock_picker):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_picker.return_value = (False, tmp_dir, "")
            resp = self.client.post("/api/system/pick-folder")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertFalse(data.get("canceled"))
            self.assertEqual(data.get("path"), str(Path(tmp_dir).resolve()))

    @patch("Backend.app._pick_folder_native")
    def test_api_pick_folder_not_a_dir(self, mock_picker):
        with tempfile.NamedTemporaryFile() as tmp_file:
            mock_picker.return_value = (False, tmp_file.name, "")
            resp = self.client.post("/api/system/pick-folder")
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertIn("not a directory", data.get("error", ""))

    @patch("Backend.app._pick_folder_native")
    def test_api_pick_folder_error(self, mock_picker):
        mock_picker.return_value = (False, "", "Something failed")
        resp = self.client.post("/api/system/pick-folder")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data.get("error"), "Something failed")

    @patch.dict("os.environ", {"RENDER": "true"})
    def test_api_pick_folder_cloud_environment(self):
        resp = self.client.post("/api/system/pick-folder")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("is_cloud"))
        self.assertEqual(data.get("path"), "./output")

    def test_results_and_writer_with_custom_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = OutputWriter(tmp_dir)
            filename = writer.save_page("https://example.com/test", "Test Page", "Page text body", 1)
            writer.finalize()

            self.assertTrue((Path(tmp_dir) / filename).exists())
            self.assertTrue((Path(tmp_dir) / "index.json").exists())

            # Test api_results endpoint reading custom output_dir
            resp = self.client.get(f"/api/results?output_dir={tmp_dir}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["total_pages"], 1)
            self.assertEqual(data["pages"][0]["file"], filename)

            # Test api_results_file endpoint reading file from custom output_dir
            file_resp = self.client.get(f"/api/results/file?file={filename}&output_dir={tmp_dir}")
            self.assertEqual(file_resp.status_code, 200)
            file_data = file_resp.get_json()
            self.assertIn("Page text body", file_data["content"])

            # Test path traversal protection
            traversal_resp = self.client.get(f"/api/results/file?file=../etc/passwd&output_dir={tmp_dir}")
            self.assertEqual(traversal_resp.status_code, 403)

            # Test api_results_download
            dl_resp = self.client.get(f"/api/results/download?output_dir={tmp_dir}")
            self.assertEqual(dl_resp.status_code, 200)
            self.assertEqual(dl_resp.mimetype, "application/zip")

            # Test api_results_clear
            clear_resp = self.client.post("/api/results/clear", json={"output_dir": tmp_dir})
            self.assertEqual(clear_resp.status_code, 200)
            self.assertGreaterEqual(clear_resp.get_json()["deleted_files"], 2)


if __name__ == "__main__":
    unittest.main()
