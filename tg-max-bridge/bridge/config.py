"""Конфигурация моста: переменные окружения + опциональный .env файл."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VALID_DIRECTIONS = ("both", "tg_to_max", "max_to_tg")


def load_dotenv(path: str | Path = ".env") -> None:
    """Мини-парсер .env: KEY=VALUE построчно, '#' — комментарий.

    Уже установленные переменные окружения имеют приоритет над файлом.
    """
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    tg_token: str
    max_token: str
    tg_chat_id: Optional[int]
    max_chat_id: Optional[int]
    direction: str = "both"
    db_path: str = "bridge.sqlite3"
    show_author: bool = True

    @property
    def discovery_mode(self) -> bool:
        """Без настроенной пары чатов мост только печатает chat_id входящих сообщений."""
        return self.tg_chat_id is None or self.max_chat_id is None

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(os.environ.get("BRIDGE_ENV_FILE", ".env"))

        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        max_token = os.environ.get("MAX_BOT_TOKEN", "").strip()
        if not tg_token or not max_token:
            raise SystemExit(
                "Нужны TELEGRAM_BOT_TOKEN и MAX_BOT_TOKEN "
                "(через переменные окружения или файл .env, см. .env.example)"
            )

        direction = os.environ.get("BRIDGE_DIRECTION", "both").strip().lower()
        if direction not in VALID_DIRECTIONS:
            raise SystemExit(
                f"BRIDGE_DIRECTION должен быть одним из {VALID_DIRECTIONS}, получено: {direction!r}"
            )

        return cls(
            tg_token=tg_token,
            max_token=max_token,
            tg_chat_id=_int_or_none(os.environ.get("TELEGRAM_CHAT_ID")),
            max_chat_id=_int_or_none(os.environ.get("MAX_CHAT_ID")),
            direction=direction,
            db_path=os.environ.get("BRIDGE_DB_PATH", "bridge.sqlite3"),
            show_author=os.environ.get("BRIDGE_SHOW_AUTHOR", "1").strip() not in ("0", "false", "no"),
        )


def _int_or_none(raw: Optional[str]) -> Optional[int]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Ожидалось число, получено: {raw!r}")
