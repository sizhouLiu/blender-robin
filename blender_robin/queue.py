from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .config import RenderConfig
from .renderer import RenderResult


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: int
    config: RenderConfig
    status: JobStatus
    priority: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result_json: str | None = None


class RenderQueue:
    def __init__(self, db_path: Path = Path("render_queue.db")) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                result_json TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status_priority
            ON jobs(status, priority DESC, created_at ASC)
        """)
        conn.commit()
        conn.close()

    def add(self, config: RenderConfig, priority: int = 0) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "INSERT INTO jobs (config_json, priority) VALUES (?, ?)",
            (json.dumps(config.to_dict()), priority),
        )
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return job_id

    def add_batch(self, configs: list[RenderConfig], priority: int = 0) -> list[int]:
        conn = sqlite3.connect(self.db_path)
        ids: list[int] = []
        for config in configs:
            cursor = conn.execute(
                "INSERT INTO jobs (config_json, priority) VALUES (?, ?)",
                (json.dumps(config.to_dict()), priority),
            )
            ids.append(cursor.lastrowid)
        conn.commit()
        conn.close()
        return ids

    def next_pending(self) -> Job | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            UPDATE jobs
            SET status = 'running', started_at = datetime('now')
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING *
        """)
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        return self._row_to_job(row) if row else None

    def complete(self, job_id: int, result: RenderResult) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE jobs
            SET status = 'completed', completed_at = datetime('now'), result_json = ?
            WHERE id = ?
            """,
            (json.dumps(result.__dict__, default=str), job_id),
        )
        conn.commit()
        conn.close()

    def fail(self, job_id: int, error: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', completed_at = datetime('now'), error_message = ?
            WHERE id = ?
            """,
            (error, job_id),
        )
        conn.commit()
        conn.close()

    def cancel(self, job_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', completed_at = datetime('now') WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        conn.close()

    def retry(self, job_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE jobs
            SET status = 'pending', started_at = NULL, completed_at = NULL,
                error_message = NULL, result_json = NULL
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()
        conn.close()

    def list_jobs(self, status: JobStatus | None = None) -> list[Job]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY priority DESC, created_at ASC",
                (status,),
            )
        else:
            cursor = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_job(row) for row in rows]

    def get_job(self, job_id: int) -> Job | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_job(row) if row else None

    def clear(self, status: JobStatus | None = None) -> int:
        conn = sqlite3.connect(self.db_path)
        if status:
            cursor = conn.execute("DELETE FROM jobs WHERE status = ?", (status,))
        else:
            cursor = conn.execute("DELETE FROM jobs")
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count

    def stats(self) -> dict[str, int]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
        stats = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return stats

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        config_dict = json.loads(row["config_json"])
        return Job(
            id=row["id"],
            config=RenderConfig.from_dict(config_dict),
            status=JobStatus(row["status"]),
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            error_message=row["error_message"],
            result_json=row["result_json"],
        )
