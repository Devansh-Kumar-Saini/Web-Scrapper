# Docker Guide

This guide covers running Website Scraper in Docker and publishing your own free,
public image that anyone can download.

The image contains Python, all Python dependencies, and a headless Chromium
browser for JavaScript rendering, so users do not have to install anything
except Docker.

---

## 1. Run the image locally

### 1.1 Install and start Docker

- macOS / Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  and open it. Wait until the whale icon says "Engine running".
- Linux: install Docker Engine and make sure the daemon is running
  (`sudo systemctl start docker`).

Check that it works:

```bash
docker --version
docker info
```

`docker info` should print server information, not an error about the daemon.

### 1.2 Build the image

From the project root (the folder containing `Dockerfile`):

```bash
docker build -t website-scraper:latest .
```

The first build downloads Chromium and takes roughly 5–15 minutes. Later builds
are much faster because Docker reuses cached layers. Expect an image around
1.5 GB — most of that is Chromium and its system libraries.

### 1.3 Start the container

```bash
docker run -d \
  --name website-scraper \
  -p 5000:5000 \
  -v "$(pwd)/output:/app/output" \
  website-scraper:latest
```

- `-d` runs it in the background.
- `-p 5000:5000` publishes the web UI on <http://localhost:5000>.
- `-v "$(pwd)/output:/app/output"` keeps scraped files on your machine after the
  container is deleted. On Windows PowerShell, use `${PWD}/output:/app/output`.
- Add `--restart unless-stopped` if you want it to start with Docker.

Open <http://localhost:5000> and start scraping.

Useful commands:

```bash
docker logs -f website-scraper     # live logs
docker stop website-scraper        # stop
docker start website-scraper       # start again
docker rm -f website-scraper       # remove the container
```

### 1.4 Test the API or Web UI
 
```bash
# One-off API request against the running container
curl "http://localhost:5000/api/scrape?url=https://example.com&format=markdown"
```

### 1.5 Docker Compose (optional)

With Docker Compose installed, this single command builds and runs everything:

```bash
docker compose up -d --build
```

Stop it with `docker compose down`.

---

## 2. Publish the image for free

You need a free registry account. There are two good choices:

| Registry | Free public images | Best for |
|---|---|---|
| **Docker Hub** | Yes, unlimited public repos | Easiest for strangers to find (`docker pull username/website-scraper`) |
| **GitHub Container Registry (GHCR)** | Yes, public packages | Automatically built by GitHub Actions from your repo |

You can publish to both. The steps below use `YOURNAME` as a placeholder — replace
it with your own username everywhere.

---

### Option A — Docker Hub (manual, recommended for your first time)

1. **Create an account** at <https://hub.docker.com> and verify your email.
2. **Create a repository**: Docker Hub → *Repositories* → *Create repository*.
   - Name: `website-scraper`
   - Visibility: **Public**
3. **Log in from your terminal**:

   ```bash
   docker login
   ```

   Enter your Docker Hub username and password. If you enabled two-factor
   authentication, create an *access token* (Account settings → Security →
   New access token) and paste that instead of your password.

4. **Tag the image** with your Docker Hub namespace:

   ```bash
   docker tag website-scraper:latest YOURNAME/website-scraper:latest
   docker tag website-scraper:latest YOURNAME/website-scraper:1.1.0
   ```

5. **Push it**:

   ```bash
   docker push YOURNAME/website-scraper:1.1.0
   docker push YOURNAME/website-scraper:latest
   ```

   The first push uploads every layer and can take a few minutes.

6. **Make sure it is public**. On the repository page, the visibility badge
   should say *Public*. If not, go to *Settings → Visibility* and change it.

7. **Test like a stranger would** — remove your local copy, then pull it back:

   ```bash
   docker rmi YOURNAME/website-scraper:latest
   docker pull YOURNAME/website-scraper:latest
   docker run -d --name website-scraper -p 5000:5000 \
     -v "$(pwd)/output:/app/output" YOURNAME/website-scraper:latest
   ```

Anyone can now use it with:

```bash
docker run -d -p 5000:5000 -v "$(pwd)/output:/app/output" YOURNAME/website-scraper:latest
```

---

### Option B — GitHub Container Registry + automatic builds (recommended long-term)

This repository already contains `.github/workflows/docker-publish.yml`. It builds
the image for **Intel/AMD (`linux/amd64`) and Apple Silicon/ARM (`linux/arm64`)**
and pushes it to GHCR every time you push to `main` or create a `v*` tag.

1. **Push the project to GitHub** (if you have not already):

   ```bash
   git add .
   git commit -m "Add Docker image and publishing workflow"
   git push origin main
   ```

2. **Let the workflow run**: open your repository on GitHub → **Actions** tab →
   *Publish Docker image*. A multi-architecture build usually takes 10–25 minutes
   the first time.

3. **Make the package public**: after a successful run, open your GitHub profile →
   **Packages** → `web-scrapper` → *Package settings* → *Change visibility* →
   **Public**. Without this step, only you can pull it.

4. **Use it**:

   ```bash
   docker pull ghcr.io/YOURNAME/web-scrapper:latest
   docker run -d -p 5000:5000 -v "$(pwd)/output:/app/output" \
     ghcr.io/YOURNAME/web-scrapper:latest
   ```

   GitHub repository names must be lowercase in image tags, which is why the
   workflow lowercases the name automatically. The default branch tag is
   `latest`; a Git tag such as `v1.1.0` also produces `1.1.0` and `1.1`.

5. **Releasing a new version**:

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

   That triggers a new build and publishes versioned tags plus `latest`.

---

### Option C — Manual multi-architecture push

Docker Desktop includes Buildx. To build and push both architectures yourself:

```bash
docker buildx create --name multiarch --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t YOURNAME/website-scraper:latest \
  -t YOURNAME/website-scraper:1.1.0 \
  --push .
```

`--push` is required for multi-platform builds; `--load` only supports a single
platform. Building the ARM variant on an Intel machine is slow because it runs
under emulation.

---

## 3. Configuration

The image supports these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Port the web server listens on inside the container |
| `SCRAPER_CONTAINER` | `1` | Set automatically; tells the UI to hide the native folder picker and use `/app/output` |

Change the published port with `-p 8080:5000`, then open <http://localhost:8080>.
If you also change `PORT`, publish the same number: `-e PORT=8080 -p 8080:8080`.

Scraped files are written to `/app/output` inside the container. Mount a volume
there as shown above, or download them from the UI's **Download ZIP** button.

---

## 4. Updating a published image

```bash
# 1. Rebuild with your changes
docker build -t YOURNAME/website-scraper:latest .

# 2. Push the new latest (and a new version tag)
docker push YOURNAME/website-scraper:latest
docker tag YOURNAME/website-scraper:latest YOURNAME/website-scraper:1.2.0
docker push YOURNAME/website-scraper:1.2.0
```

Users update with `docker pull YOURNAME/website-scraper:latest` and restart the
container. With GHCR, pushing a new Git tag does this automatically.

---

## 5. Troubleshooting

**`0.0.0.0 refused to connect` or `ERR_CONNECTION_REFUSED` in browser**:
- **Do not open `0.0.0.0:5000`**: Open **`http://localhost:5000`** or **`http://127.0.0.1:5000`**. Gunicorn logs `Listening at: http://0.0.0.0:5000` because it binds to all internal network interfaces, but modern browsers (Chrome 128+, Safari, Edge) block `0.0.0.0` as an IP destination for security.
- **Port mapping**: Ensure you started the container with `-p 5000:5000` or used `docker compose up`. If `-p 5000:5000` is omitted, the port is only listening inside the container and cannot be reached from your machine.

**`Cannot connect to the Docker daemon`** — Docker Desktop is not running. Open it
and wait for the engine to start.

**`port is already allocated`** — something else uses port 5000. Publish another
one: `-p 8080:5000`.

**`permission denied` writing to `/app/output` (Linux)** — the mounted folder must
be writable by the container user. Use a folder you own, or run with
`--user "$(id -u):$(id -g)"`.

**JavaScript rendering fails** — rebuild without the cache:
`docker build --no-cache -t website-scraper .`. The browser is installed at
`/ms-playwright` during the build.

**Image is large / build is slow** — this is normal; Chromium and its libraries
account for most of it. Ask users to pull the prebuilt image instead of building.

**`unauthorized` when pushing** — run `docker login` again, or use a Docker Hub
access token instead of your account password.

**GHCR pull is denied** — the package is still private. Set its visibility to
public in the package settings.
