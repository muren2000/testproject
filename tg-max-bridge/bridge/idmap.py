"""Соответствие id сообщений Telegram <-> MAX (для правок, удалений и ответов).

SQLite без внешних зависимостей: на личных объёмах сообщений блокирующие
запросы занимают доли миллисекунды, поэтому обходимся без async-обёртки.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS msg_map (
    tg_message_id INTEGER NOT NULL,
    max_mid       TEXT    NOT NULL,
    origin        TEXT    NOT NULL CHECK (origin IN ('tg', 'max')),
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_map_tg  ON msg_map (tg_message_id);
CREATE INDEX IF NOT EXISTS idx_msg_map_max ON msg_map (max_mid);
"""


class IdMap:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def add(self, tg_message_id: int, max_mid: str, origin: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO msg_map (tg_message_id, max_mid, origin, created_at) VALUES (?, ?, ?, ?)",
                (tg_message_id, max_mid, origin, int(time.time())),
            )
            self._conn.commit()

    def max_for_tg(self, tg_message_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT max_mid FROM msg_map WHERE tg_message_id = ? ORDER BY rowid DESC LIMIT 1",
                (tg_message_id,),
            ).fetchone()
        return row[0] if row else None

    def tg_for_max(self, max_mid: str) -> Optional[int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT tg_message_id FROM msg_map WHERE max_mid = ? ORDER BY rowid DESC LIMIT 1",
                (max_mid,),
            ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
