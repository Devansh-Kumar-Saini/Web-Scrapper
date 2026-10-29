FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser and its system dependencies
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

ENV PORT=5000
EXPOSE 5000

# Run with Gunicorn (1 worker, 8 threads for SSE and scraping concurrency)
CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 300"]
