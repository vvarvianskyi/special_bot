"""SQLite-хранилище снапшотов (п.3.3 ТЗ)."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "promo_monitor.db"


@dataclass
class Snapshot:
    site_id: str
    timestamp: str
    raw_text: str
    hash: str
    # Строка акции -> ссылка на неё. Хранится отдельно от raw_text и в хэш не
    # входит — смена одного только URL не должна считаться изменением акции.
    links: Optional[Dict[str, str]] = None


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
                hash TEXT NOT NULL,
                links_json TEXT
            )
            """
        )
        # Миграция существующей базы: колонка links_json появилась позже
        # (ссылки на акции в отчёте). ADD COLUMN не трогает старые строки —
        # у них просто NULL, т.е. "ссылок не сохранено".
        columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
        if "links_json" not in columns:
            conn.execute("ALTER TABLE snapshots ADD COLUMN links_json TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_site_id_timestamp ON snapshots (site_id, timestamp)"
        )
        conn.commit()


def save_snapshot(snapshot: Snapshot, db_path: Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        links_json = json.dumps(snapshot.links, ensure_ascii=False) if snapshot.links else None
        conn.execute(
            "INSERT INTO snapshots (site_id, timestamp, raw_text, hash, links_json) VALUES (?, ?, ?, ?, ?)",
            (snapshot.site_id, snapshot.timestamp, snapshot.raw_text, snapshot.hash, links_json),
        )
        conn.commit()


def get_version_since(site_id: str, content_hash: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[str]:
    """Когда эта версия промо появилась на сайте впервые — начало непрерывной
    серии снапшотов с таким хэшем.

    Снапшот пишется каждый прогон, поэтому timestamp последнего снапшота — это
    "проверено час назад", а не "акция сменилась час назад". Для отчёта нужна
    именно дата появления версии: берём последний снапшот с ДРУГИМ хэшем и
    первый снапшот с нашим хэшем после него.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT MIN(timestamp) FROM snapshots
            WHERE site_id = ? AND hash = ? AND timestamp > COALESCE(
                (SELECT MAX(timestamp) FROM snapshots WHERE site_id = ? AND hash != ?), ''
            )
            """,
            (site_id, content_hash, site_id, content_hash),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_last_snapshot(site_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[Snapshot]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT site_id, timestamp, raw_text, hash, links_json FROM snapshots "
            "WHERE site_id = ? ORDER BY timestamp DESC LIMIT 1",
            (site_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        links = None
        if row[4]:
            try:
                links = json.loads(row[4])
            except ValueError:
                links = None  # битый JSON — не повод ронять прогон, просто без ссылок
        return Snapshot(site_id=row[0], timestamp=row[1], raw_text=row[2], hash=row[3], links=links)
