"""Command-line entry point for the website content scraper."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root and Backend directory are importable when running the file
# directly (python main.py) or from an editable install.
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "Backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from Backend.cli import main, parse_args, run  # noqa: E402

__all__ = ["main", "parse_args", "run"]

if __name__ == "__main__":
    raise SystemExit(main())
