"""Lazy, reusable Playwright renderer for JavaScript-heavy pages."""

from __future__ import annotations

import logging
import subprocess
import sys

try:
    from .config import RENDER_TIMEOUT_MS, USER_AGENT
except ImportError:  # pragma: no cover - direct script execution
    from config import RENDER_TIMEOUT_MS, USER_AGENT


class PlaywrightRenderer:
    """Owns a single Chromium instance and reuses pages for each render.

    Playwright is imported lazily so the scraper keeps working without it, and
    the browser is only launched on the first render request.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._playwright_ctx = None
        self._playwright = None
        self._browser = None

    def _get_browser(self):
        if self._browser is not None:
            return self._browser

        from playwright.sync_api import sync_playwright

        if self._playwright_ctx is None:
            self._playwright_ctx = sync_playwright()
            self._playwright = self._playwright_ctx.start()

        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        try:
            self._browser = self._playwright.chromium.launch(headless=True, args=launch_args)
        except Exception as launch_exc:
            err_msg = str(launch_exc)
            if "Executable doesn't exist" in err_msg or "playwright install" in err_msg:
                self.logger.warning("Chromium executable missing. Attempting on-demand `playwright install chromium`...")
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode == 0:
                    self.logger.info("Chromium successfully installed on-demand.")
                    self._browser = self._playwright.chromium.launch(headless=True, args=launch_args)
                else:
                    self.logger.error("Failed to install Chromium on-demand: %s", result.stderr)
                    raise
            else:
                raise
        return self._browser

    def render(self, url: str, timeout_ms: int | None = None) -> str | None:
        """Return the rendered HTML for ``url``, or None when rendering fails."""
        try:
            import playwright  # noqa: F401
        except ImportError:
            self.logger.warning(
                "JavaScript rendering unavailable; install with "
                "`pip install playwright && playwright install chromium`."
            )
            return None

        try:
            browser = self._get_browser()
            page = browser.new_page(user_agent=USER_AGENT)
            try:
                # Block heavy assets to render fast and keep memory usage low.
                page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "media", "font"}
                    else route.continue_(),
                )
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms or RENDER_TIMEOUT_MS,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=1500)
                except Exception:
                    pass
                return page.content()
            finally:
                page.close()
        except Exception as exc:
            self.logger.warning("JavaScript rendering failed for %s: %s", url, exc)
            return None

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright_ctx is not None:
            try:
                self._playwright_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._playwright_ctx = None
            self._playwright = None

    def __enter__(self) -> PlaywrightRenderer:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
