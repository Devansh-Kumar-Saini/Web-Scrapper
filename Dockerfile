# syntax=docker/dockerfile:1

# Playwright's browser download is pinned to a stable cache location so the
# browser installed at build time is found again at runtime.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="Website Scraper" \
      org.opencontainers.image.description="Free, self-hosted website scraper with Markdown/JSON output, REST API and web UI." \
      org.opencontainers.image.url="https://github.com/Devansh-Kumar-Saini/Web-Scrapper" \
      org.opencontainers.image.source="https://github.com/Devansh-Kumar-Saini/Web-Scrapper" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SCRAPER_CONTAINER=1 \
    PORT=5000

WORKDIR /app

# libatomic1 is required by the Node.js binary bundled with Playwright; the
# python:slim base image does not include it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so this layer is cached when only app code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium plus all the OS libraries it needs for JavaScript rendering.
# --only-shell installs just the headless browser (the app never opens a visible
# window), saving ~400 MB over the full Chromium build.
RUN playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code (see .dockerignore for what is excluded).
COPY . .

# Output directory is created up front so a mounted volume has a writable target.
RUN mkdir -p /app/output

EXPOSE 5000

# Container-friendly health check: the web server answering means the app is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3)" || exit 1

# One worker + threads keeps the in-memory job state and SSE streams consistent.
CMD ["sh", "-c", "printf '\\n=======================================================\\n  Website Scraper Container Ready\\n  --> Open in browser: http://localhost:%s (or http://127.0.0.1:%s)\\n  (!) Do NOT open 0.0.0.0 in browser (blocked by macOS & Chrome)\\n  (!) Ensure port is published: docker run -p %s:%s or docker compose up\\n=======================================================\\n\\n' \"${PORT}\" \"${PORT}\" \"${PORT}\" \"${PORT}\" && exec gunicorn Backend.app:app --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 300"]
