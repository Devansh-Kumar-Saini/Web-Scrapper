"""Local, persistent crawl state: job metadata, queue, checkpoint, and DLQ.

This is the offline alternative to a Redis/Celery stack.  Everything lives in a
single SQLite file (``<output>/.scraper/crawl_state.db`` by default), which means:

* crawls survive crashes, network drops, and container restarts;
* multiple crawler processes can share the same state file (put it on a shared
  volume) and coordinate through atomic claims instead of duplicating work;
* no server, account, API key, or credential is required.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    from .retry import CATEGORY_UNKNOWN
except ImportError:  # pragma: no cover - direct script execution
    from retry import CATEGORY_UNKNOWN


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: str | bytes) -> str:
    """SHA-256 digest used for delta/change detection."""
    data = content.encode("utf-8", errors="replace") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _SQLiteBase:
    """Thread-safe SQLite helper with WAL, busy timeout, and retry-on-lock."""

    _SCHEMA = ""

    def __init__(self, db_path: str | Path, logger: logging.Logger | None = None) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger(__name__)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._connections: list[sqlite3.Connection] = []
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        with self._lock:
            self._connections.append(conn)
        return conn

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(self._SCHEMA)
        # The thread-local connection for the constructor thread is not needed.
        self._local.conn = None

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Run a serialized write transaction, retrying short lock contention."""
        conn = self._conn()
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise last_error

    def close(self) -> None:
        with self._lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
            self._local.conn = None


_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    output_dir TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    stats_json TEXT NOT NULL DEFAULT '{}',
    resume_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC);
"""

_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    seed_domain TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL DEFAULT 0,
    claimed_by TEXT,
    claimed_at REAL,
    error_category TEXT,
    error_message TEXT,
    status_code INTEGER,
    sitemap_lastmod TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, url)
);
CREATE INDEX IF NOT EXISTS idx_queue_ready
    ON queue(job_id, state, available_at, priority);

CREATE TABLE IF NOT EXISTS visited (
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    status_code INTEGER,
    content_hash TEXT NOT NULL DEFAULT '',
    etag TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    file TEXT NOT NULL DEFAULT '',
    error_category TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (job_id, url)
);

CREATE TABLE IF NOT EXISTS failures (
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT 'unknown',
    status_code INTEGER,
    message TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 1,
    failed_at TEXT NOT NULL,
    retryable INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (job_id, url)
);
CREATE INDEX IF NOT EXISTS idx_failures_job ON failures(job_id, failed_at DESC);
"""

_DELTA_SCHEMA = """
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL DEFAULT '',
    etag TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL DEFAULT '',
    sitemap_lastmod TEXT NOT NULL DEFAULT '',
    status_code INTEGER,
    fetched_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    file TEXT NOT NULL DEFAULT '',
    links TEXT NOT NULL DEFAULT '[]'
);
"""


class CrawlStore(_SQLiteBase):
    """SQLite-backed queue, checkpoint, job registry, and dead-letter queue."""

    _SCHEMA = _JOBS_SCHEMA + _QUEUE_SCHEMA

    # --- jobs ---------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        output_dir: str = "",
        config: dict[str, Any] | None = None,
        status: str = "running",
        resume_of: str | None = None,
    ) -> None:
        now = utc_now_iso()
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO jobs (job_id, created_at, updated_at, status, output_dir, config_json, stats_json, resume_of)
                VALUES (?, ?, ?, ?, ?, ?, '{}', ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    status=excluded.status,
                    output_dir=CASE WHEN excluded.output_dir != '' THEN excluded.output_dir ELSE jobs.output_dir END,
                    config_json=CASE WHEN excluded.config_json NOT IN ('', '{}') THEN excluded.config_json ELSE jobs.config_json END,
                    resume_of=COALESCE(excluded.resume_of, jobs.resume_of)
                """,
                (
                    job_id,
                    now,
                    now,
                    status,
                    output_dir or "",
                    json.dumps(config or {}, ensure_ascii=False),
                    resume_of,
                ),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stats: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        output_dir: str | None = None,
    ) -> None:
        fields: list[str] = ["updated_at=?"]
        values: list[Any] = [utc_now_iso()]
        if status is not None:
            fields.append("status=?")
            values.append(status)
        if stats is not None:
            fields.append("stats_json=?")
            values.append(json.dumps(stats, ensure_ascii=False))
        if config is not None:
            fields.append("config_json=?")
            values.append(json.dumps(config, ensure_ascii=False))
        if output_dir is not None:
            fields.append("output_dir=?")
            values.append(output_dir)
        values.append(job_id)
        with self._write() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id=?", values)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn().execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
        return [self._job_row(row) for row in rows]

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["config"] = json.loads(item.pop("config_json", "{}") or "{}")
        except (TypeError, ValueError):
            item["config"] = {}
        try:
            item["stats"] = json.loads(item.pop("stats_json", "{}") or "{}")
        except (TypeError, ValueError):
            item["stats"] = {}
        return item

    # --- queue --------------------------------------------------------------

    def enqueue_many(
        self,
        job_id: str,
        entries: Iterable[tuple[str, int, str] | tuple[str, int, str, str] | dict[str, Any]],
        *,
        max_total: int = 0,
    ) -> int:
        """Add URLs to the queue, never duplicating an existing job/url pair.

        ``max_total`` caps the combined queue + visited size atomically, which
        keeps the page cap correct even when several processes enqueue at once.
        """
        inserted = 0
        now_iso = utc_now_iso()
        with self._write() as conn:
            if max_total and max_total > 0:
                row = conn.execute(
                    "SELECT COUNT(*) AS total FROM ("
                    "SELECT url FROM queue WHERE job_id=? "
                    "UNION "
                    "SELECT url FROM visited WHERE job_id=?"
                    ")",
                    (job_id, job_id),
                ).fetchone()
                total = int(row["total"] if row else 0)
            else:
                total = 0

            for entry in entries:
                if max_total and max_total > 0 and total >= max_total:
                    break
                if isinstance(entry, dict):
                    url = str(entry.get("url") or "")
                    depth = int(entry.get("depth", 0) or 0)
                    seed_domain = str(entry.get("seed_domain") or "")
                    lastmod = str(entry.get("lastmod") or "")
                    priority = int(entry.get("priority", 0) or 0)
                else:
                    url = str(entry[0] or "")
                    depth = int(entry[1] if len(entry) > 1 else 0 or 0)
                    seed_domain = str(entry[2] if len(entry) > 2 else "")
                    lastmod = str(entry[3] if len(entry) > 3 else "")
                    priority = int(entry[4] if len(entry) > 4 else 0)
                if not url:
                    continue
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO queue
                        (job_id, url, depth, seed_domain, priority, state, attempts,
                         available_at, created_at, updated_at, sitemap_lastmod)
                    VALUES (?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?)
                    """,
                    (job_id, url, depth, seed_domain, priority, now_iso, now_iso, lastmod),
                )
                if cursor.rowcount:
                    inserted += 1
                    total += 1
        return inserted

    def enqueue(
        self,
        job_id: str,
        url: str,
        depth: int = 0,
        seed_domain: str = "",
        lastmod: str = "",
        priority: int = 0,
        max_total: int = 0,
    ) -> bool:
        return (
            self.enqueue_many(
                job_id,
                [(url, depth, seed_domain, lastmod, priority)],
                max_total=max_total,
            )
            > 0
        )

    def claim(self, job_id: str, worker_id: str = "local", lease_seconds: float = 180.0) -> dict[str, Any] | None:
        """Atomically claim the next ready URL for this worker."""
        now = time.time()
        now_iso = utc_now_iso()
        with self._write() as conn:
            # Recover work from workers that died mid-request.
            conn.execute(
                """
                UPDATE queue
                SET state='pending', claimed_by=NULL, claimed_at=NULL, updated_at=?
                WHERE job_id=? AND state='claimed' AND COALESCE(claimed_at, 0) < ?
                """,
                (now_iso, job_id, now - (lease_seconds if lease_seconds > 0 else 180.0)),
            )
            row = conn.execute(
                """
                SELECT * FROM queue
                WHERE job_id=? AND state='pending' AND available_at <= ?
                ORDER BY priority DESC, rowid ASC
                LIMIT 1
                """,
                (job_id, now),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE queue
                SET state='claimed', claimed_by=?, claimed_at=?, updated_at=?
                WHERE job_id=? AND url=? AND state='pending'
                """,
                (worker_id, now, now_iso, job_id, row["url"]),
            )
            item = dict(row)
            item["state"] = "claimed"
            item["claimed_by"] = worker_id
            item["claimed_at"] = now
            return item

    def claim_many(
        self,
        job_id: str,
        worker_id: str = "local",
        limit: int = 1,
        lease_seconds: float = 180.0,
    ) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for _ in range(max(0, int(limit))):
            item = self.claim(job_id, worker_id=worker_id, lease_seconds=lease_seconds)
            if item is None:
                break
            claimed.append(item)
        return claimed

    def defer(self, job_id: str, url: str, delay_seconds: float, reason: str = "") -> None:
        """Return a claimed URL to the queue for a later attempt."""
        with self._write() as conn:
            conn.execute(
                """
                UPDATE queue
                SET state='pending', claimed_by=NULL, claimed_at=NULL,
                    available_at=?, updated_at=?, error_message=?
                WHERE job_id=? AND url=? AND state='claimed'
                """,
                (time.time() + max(0.0, delay_seconds), utc_now_iso(), reason, job_id, url),
            )

    def complete(
        self,
        job_id: str,
        url: str,
        *,
        depth: int = 0,
        status: str = "done",
        status_code: int | None = None,
        hash_value: str = "",
        etag: str = "",
        last_modified: str = "",
        title: str = "",
        word_count: int = 0,
        file: str = "",
        attempts: int = 1,
    ) -> None:
        now = utc_now_iso()
        with self._write() as conn:
            conn.execute(
                """
                UPDATE queue SET state=?, updated_at=? WHERE job_id=? AND url=?
                """,
                ("done" if status == "done" else status, now, job_id, url),
            )
            conn.execute(
                """
                INSERT INTO visited
                    (job_id, url, depth, fetched_at, status, status_code, content_hash,
                     etag, last_modified, title, word_count, file, attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, url) DO UPDATE SET
                    fetched_at=excluded.fetched_at,
                    status=excluded.status,
                    status_code=COALESCE(excluded.status_code, visited.status_code),
                    content_hash=CASE WHEN excluded.content_hash != '' THEN excluded.content_hash ELSE visited.content_hash END,
                    etag=CASE WHEN excluded.etag != '' THEN excluded.etag ELSE visited.etag END,
                    last_modified=CASE WHEN excluded.last_modified != '' THEN excluded.last_modified ELSE visited.last_modified END,
                    title=CASE WHEN excluded.title != '' THEN excluded.title ELSE visited.title END,
                    word_count=CASE WHEN excluded.word_count > 0 THEN excluded.word_count ELSE visited.word_count END,
                    file=CASE WHEN excluded.file != '' THEN excluded.file ELSE visited.file END,
                    attempts=excluded.attempts
                """,
                (
                    job_id,
                    url,
                    depth,
                    now,
                    status,
                    status_code,
                    hash_value,
                    etag,
                    last_modified,
                    title,
                    word_count,
                    file,
                    attempts,
                ),
            )

    def mark_skipped(
        self,
        job_id: str,
        url: str,
        reason: str,
        *,
        depth: int = 0,
        status_code: int | None = None,
        category: str = "",
    ) -> None:
        now = utc_now_iso()
        with self._write() as conn:
            conn.execute(
                "UPDATE queue SET state='skipped', error_category=?, error_message=?, updated_at=? WHERE job_id=? AND url=?",
                (category or reason, reason, now, job_id, url),
            )
            conn.execute(
                """
                INSERT INTO visited
                    (job_id, url, depth, fetched_at, status, status_code, error_category, error_message)
                VALUES (?, ?, ?, ?, 'skipped', ?, ?, ?)
                ON CONFLICT(job_id, url) DO UPDATE SET
                    fetched_at=excluded.fetched_at,
                    status='skipped',
                    status_code=COALESCE(excluded.status_code, visited.status_code),
                    error_category=excluded.error_category,
                    error_message=excluded.error_message
                """,
                (job_id, url, depth, now, status_code, category or reason, reason),
            )

    def fail(
        self,
        job_id: str,
        url: str,
        *,
        depth: int = 0,
        category: str = CATEGORY_UNKNOWN,
        message: str = "",
        status_code: int | None = None,
        retryable: bool = True,
        delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Record a failure. Retry later or move it to the DLQ."""
        now_iso = utc_now_iso()
        with self._write() as conn:
            row = conn.execute(
                "SELECT attempts, depth FROM queue WHERE job_id=? AND url=?", (job_id, url)
            ).fetchone()
            attempts = int(row["attempts"] if row else 0) + 1
            failed_depth = int(row["depth"] if row else depth)
            if retryable:
                conn.execute(
                    """
                    UPDATE queue
                    SET state='pending', attempts=?, available_at=?, claimed_by=NULL,
                        claimed_at=NULL, error_category=?, error_message=?, status_code=?,
                        updated_at=?
                    WHERE job_id=? AND url=?
                    """,
                    (
                        attempts,
                        time.time() + max(0.0, delay_seconds),
                        category,
                        message,
                        status_code,
                        now_iso,
                        job_id,
                        url,
                    ),
                )
                return {"retry": True, "attempts": attempts, "delay": delay_seconds}

            conn.execute(
                """
                UPDATE queue
                SET state='failed', attempts=?, claimed_by=NULL, claimed_at=NULL,
                    error_category=?, error_message=?, status_code=?, updated_at=?
                WHERE job_id=? AND url=?
                """,
                (attempts, category, message, status_code, now_iso, job_id, url),
            )
            conn.execute(
                """
                INSERT INTO failures
                    (job_id, url, depth, error_category, status_code, message, attempts, failed_at, retryable)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(job_id, url) DO UPDATE SET
                    depth=excluded.depth,
                    error_category=excluded.error_category,
                    status_code=excluded.status_code,
                    message=excluded.message,
                    attempts=excluded.attempts,
                    failed_at=excluded.failed_at
                """,
                (job_id, url, failed_depth, category, status_code, message, attempts, now_iso),
            )
            return {"retry": False, "attempts": attempts, "delay": 0.0}

    def requeue_failed(self, job_id: str) -> int:
        """Move every DLQ entry back to pending and return the count."""
        now = time.time()
        now_iso = utc_now_iso()
        with self._write() as conn:
            rows = conn.execute("SELECT url, depth FROM failures WHERE job_id=?", (job_id,)).fetchall()
            for row in rows:
                cursor = conn.execute(
                    """
                    UPDATE queue
                    SET state='pending', attempts=0, available_at=?, claimed_by=NULL,
                        claimed_at=NULL, error_category='', error_message='', updated_at=?
                    WHERE job_id=? AND url=?
                    """,
                    (now, now_iso, job_id, row["url"]),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO queue
                            (job_id, url, depth, seed_domain, priority, state, attempts,
                             available_at, created_at, updated_at)
                        VALUES (?, ?, ?, '', 0, 'pending', 0, ?, ?, ?)
                        """,
                        (job_id, row["url"], int(row["depth"] or 0), now, now_iso, now_iso),
                    )
            conn.execute("DELETE FROM failures WHERE job_id=?", (job_id,))
            return len(rows)

    def failures(self, job_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM failures WHERE job_id=? ORDER BY failed_at DESC LIMIT ?",
            (job_id, max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def queue_stats(self, job_id: str) -> dict[str, Any]:
        rows = self._conn().execute(
            "SELECT state, COUNT(*) AS count FROM queue WHERE job_id=? GROUP BY state", (job_id,)
        ).fetchall()
        counts = {row["state"]: int(row["count"]) for row in rows}
        failures = self._conn().execute(
            "SELECT COUNT(*) AS count FROM failures WHERE job_id=?", (job_id,)
        ).fetchone()
        visited = self._conn().execute(
            "SELECT COUNT(*) AS count FROM visited WHERE job_id=?", (job_id,)
        ).fetchone()
        pending = counts.get("pending", 0)
        return {
            "pending": pending,
            "claimed": counts.get("claimed", 0),
            "done": counts.get("done", 0),
            "unchanged": counts.get("unchanged", 0),
            "skipped": counts.get("skipped", 0),
            "failed": counts.get("failed", 0),
            "dlq": int(failures["count"] if failures else 0),
            "visited": int(visited["count"] if visited else 0),
            "total": sum(counts.values()),
        }

    def next_available_in(self, job_id: str) -> float | None:
        """Seconds until a delayed retry becomes ready, or None if none wait."""
        row = self._conn().execute(
            "SELECT MIN(available_at) AS next FROM queue WHERE job_id=? AND state='pending'",
            (job_id,),
        ).fetchone()
        if row is None or row["next"] is None:
            return None
        return max(0.0, float(row["next"]) - time.time())

    def reset_claimed(self, job_id: str) -> int:
        """Return claims from a previous (crashed) worker to the queue."""
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE queue SET state='pending', claimed_by=NULL, claimed_at=NULL, updated_at=? "
                "WHERE job_id=? AND state='claimed'",
                (utc_now_iso(), job_id),
            )
            return int(cursor.rowcount or 0)

    def is_visited(self, job_id: str, url: str) -> bool:
        row = self._conn().execute(
            "SELECT 1 FROM visited WHERE job_id=? AND url=? LIMIT 1", (job_id, url)
        ).fetchone()
        return row is not None

    def set_file(self, job_id: str, url: str, file: str) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE visited SET file=? WHERE job_id=? AND url=?", (file, job_id, url)
            )

    def reset_queue(self, job_id: str) -> int:
        """Requeue all non-skipped rows (used by manual full retries)."""
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE queue SET state='pending', attempts=0, available_at=0, "
                "claimed_by=NULL, claimed_at=NULL, error_category='', error_message='' "
                "WHERE job_id=? AND state IN ('failed', 'done', 'skipped')",
                (job_id,),
            )
            conn.execute("DELETE FROM failures WHERE job_id=?", (job_id,))
            conn.execute("DELETE FROM visited WHERE job_id=?", (job_id,))
            return int(cursor.rowcount or 0)


class DeltaCache(_SQLiteBase):
    """Per-URL content hashes, ETags, and Last-Modified timestamps."""

    _SCHEMA = _DELTA_SCHEMA

    def __init__(self, db_path: str | Path, logger: logging.Logger | None = None) -> None:
        super().__init__(db_path, logger)
        # Databases created by earlier builds may not have the links column yet.
        with self._write() as conn:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(page_cache)").fetchall()
            }
            if "links" not in columns:
                conn.execute("ALTER TABLE page_cache ADD COLUMN links TEXT NOT NULL DEFAULT '[]'")

    def get(self, url: str) -> dict[str, Any] | None:
        row = self._conn().execute("SELECT * FROM page_cache WHERE url=?", (url,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        try:
            links = json.loads(record.get("links") or "[]")
        except (TypeError, ValueError):
            links = []
        record["links"] = links if isinstance(links, list) else []
        return record

    def has(self, url: str) -> bool:
        return self.get(url) is not None

    def conditional_headers(self, url: str) -> dict[str, str]:
        record = self.get(url)
        if not record:
            return {}
        headers: dict[str, str] = {}
        if record.get("etag"):
            headers["If-None-Match"] = str(record["etag"])
        if record.get("last_modified"):
            headers["If-Modified-Since"] = str(record["last_modified"])
        return headers

    def should_skip_before_fetch(self, url: str, sitemap_lastmod: str | None = None) -> bool:
        """Use a sitemap ``lastmod`` to avoid the request entirely when unchanged."""
        if not sitemap_lastmod:
            return False
        record = self.get(url)
        if not record or not record.get("content_hash"):
            return False
        cached = _parse_timestamp(record.get("sitemap_lastmod")) or _parse_timestamp(record.get("fetched_at"))
        incoming = _parse_timestamp(sitemap_lastmod)
        if cached is None or incoming is None:
            return False
        return cached >= incoming

    def is_unchanged(self, url: str, hash_value: str) -> bool:
        record = self.get(url)
        return bool(record and record.get("content_hash") and record["content_hash"] == hash_value)

    def record(
        self,
        url: str,
        *,
        hash_value: str = "",
        etag: str = "",
        last_modified: str = "",
        status_code: int | None = None,
        sitemap_lastmod: str = "",
        title: str = "",
        word_count: int = 0,
        file: str = "",
        links: list[str] | None = None,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO page_cache
                    (url, content_hash, etag, last_modified, sitemap_lastmod, status_code,
                     fetched_at, title, word_count, file, links)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash=CASE WHEN excluded.content_hash != '' THEN excluded.content_hash ELSE page_cache.content_hash END,
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    sitemap_lastmod=CASE WHEN excluded.sitemap_lastmod != '' THEN excluded.sitemap_lastmod ELSE page_cache.sitemap_lastmod END,
                    status_code=COALESCE(excluded.status_code, page_cache.status_code),
                    fetched_at=excluded.fetched_at,
                    title=CASE WHEN excluded.title != '' THEN excluded.title ELSE page_cache.title END,
                    word_count=CASE WHEN excluded.word_count > 0 THEN excluded.word_count ELSE page_cache.word_count END,
                    file=CASE WHEN excluded.file != '' THEN excluded.file ELSE page_cache.file END,
                    links=CASE WHEN excluded.links NOT IN ('', '[]') THEN excluded.links ELSE page_cache.links END
                """,
                (
                    url,
                    hash_value,
                    etag,
                    last_modified,
                    sitemap_lastmod,
                    status_code,
                    utc_now_iso(),
                    title,
                    word_count,
                    file,
                    json.dumps(list(links or []), ensure_ascii=False),
                ),
            )

    def touch(
        self,
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
        status_code: int | None = None,
        sitemap_lastmod: str = "",
    ) -> None:
        """Refresh cache validators after a 304 without discarding the hash."""
        with self._write() as conn:
            conn.execute(
                """
                UPDATE page_cache
                SET fetched_at=?, status_code=COALESCE(?, status_code),
                    etag=CASE WHEN ? != '' THEN ? ELSE etag END,
                    last_modified=CASE WHEN ? != '' THEN ? ELSE last_modified END,
                    sitemap_lastmod=CASE WHEN ? != '' THEN ? ELSE sitemap_lastmod END
                WHERE url=?
                """,
                (
                    utc_now_iso(),
                    status_code,
                    etag,
                    etag,
                    last_modified,
                    last_modified,
                    sitemap_lastmod,
                    sitemap_lastmod,
                    url,
                ),
            )

    def set_file(self, url: str, file: str) -> None:
        with self._write() as conn:
            conn.execute("UPDATE page_cache SET file=? WHERE url=?", (file, url))

    def stats(self) -> dict[str, Any]:
        row = self._conn().execute(
            "SELECT COUNT(*) AS total, MAX(fetched_at) AS last_fetch FROM page_cache"
        ).fetchone()
        return {
            "cached_urls": int(row["total"] if row else 0),
            "last_fetch": (row["last_fetch"] if row else None),
        }

    def clear(self) -> int:
        with self._write() as conn:
            cursor = conn.execute("DELETE FROM page_cache")
            return int(cursor.rowcount or 0)


def default_state_path(output_dir: str | Path) -> Path:
    """Canonical local state database location for an output directory."""
    return Path(output_dir).expanduser().resolve() / ".scraper" / "crawl_state.db"


def format_duration(seconds: float) -> str:
    """Small helper used in logs and API payloads."""
    return str(timedelta(seconds=max(0, int(seconds))))
