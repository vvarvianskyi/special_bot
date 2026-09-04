"""SQLite-хранилище снапшотов (п.3.3 ТЗ)."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "promo_monitor.db"


@dataclass
class Snapshot:
    site_id: str
    timestamp: str
    raw_text: str
    hash: str


@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_site_id_timestamp ON snapshots (site_id, timestamp)"
        )
        conn.commit()


def save_snapshot(snapshot: Snapshot, db_path: Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots (site_id, timestamp, raw_text, hash) VALUES (?, ?, ?, ?)",
            (snapshot.site_id, snapshot.timestamp, snapshot.raw_text, snapshot.hash),
        )
        conn.commit()


def get_last_snapshot(site_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[Snapshot]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT site_id, timestamp, raw_text, hash FROM snapshots "
            "WHERE site_id = ? ORDER BY timestamp DESC LIMIT 1",
            (site_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Snapshot(site_id=row[0], timestamp=row[1], raw_text=row[2], hash=row[3])
