"""Тонкий клиент Telegram Bot API (https://core.telegram.org/bots/api).

Только сырые HTTP-запросы через aiohttp — весь трафик виден и проверяем.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

import aiohttp

log = logging.getLogger("bridge.tg")

TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024


class TelegramError(Exception):
    def __init__(self, description: str, code: int = 0):
        super().__init__(f"[{code}] {description}")
        self.code = code
        self.description = description


class TelegramClient:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self._session = session

    async def call(self, method: str, /, _files: Optional[dict[str, tuple[str, bytes]]] = None,
                   **params: Any) -> Any:
        """Вызов метода Bot API. _files -> multipart, иначе обычная форма."""
        url = f"{self._base}/{method}"
        clean = {k: v for k, v in params.items() if v is not None}

        for attempt in range(5):
            if _files:
                data = aiohttp.FormData()
                for key, value in clean.items():
                    data.add_field(key, str(value))
                for key, (filename, blob) in _files.items():
                    data.add_field(key, blob, filename=filename)
                resp = await self._session.post(url, data=data)
            else:
                resp = await self._session.post(url, json=clean)

            payload = await resp.json(content_type=None)
            if payload.get("ok"):
                return payload["result"]

            # 429 — подождать сколько просят и повторить
            retry_after = (payload.get("parameters") or {}).get("retry_after")
            if resp.status == 429 and retry_after is not None:
                log.warning("Telegram: лимит запросов, ждём %s с", retry_after)
                await asyncio.sleep(float(retry_after) + 0.5)
                continue

            raise TelegramError(payload.get("description", "unknown"), resp.status)

        raise TelegramError("превышено число повторов после 429", 429)

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def updates(self, allowed: list[str]) -> AsyncIterator[dict]:
        """Бесконечный long polling getUpdates."""
        offset: Optional[int] = None
        while True:
            try:
                batch = await self.call(
                    "getUpdates", offset=offset, timeout=25,
                    allowed_updates=allowed,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("Telegram getUpdates: %s — повтор через 3 с", e)
                await asyncio.sleep(3)
                continue
            except TelegramError as e:
                log.error("Telegram getUpdates: %s — повтор через 5 с", e)
                await asyncio.sleep(5)
                continue
            for upd in batch:
                offset = upd["update_id"] + 1
                yield upd

    async def download_file(self, file_id: str) -> tuple[str, bytes]:
        """Скачивает файл по file_id, возвращает (имя, содержимое)."""
        info = await self.call("getFile", file_id=file_id)
        path = info["file_path"]
        async with self._session.get(f"{self._file_base}/{path}") as resp:
            resp.raise_for_status()
            return path.rsplit("/", 1)[-1], await resp.read()

    # --- отправка ---

    async def send_text(self, chat_id: int, text: str,
                        reply_to: Optional[int] = None) -> dict:
        return await self.call(
            "sendMessage", chat_id=chat_id, text=text[:TG_TEXT_LIMIT],
            reply_to_message_id=reply_to, allow_sending_without_reply=True,
        )

    async def send_media(self, chat_id: int, kind: str, filename: str, blob: bytes,
                         caption: Optional[str] = None,
                         reply_to: Optional[int] = None) -> dict:
        """kind: photo | document | audio | video | voice."""
        method = {
            "photo": "sendPhoto", "document": "sendDocument",
            "audio": "sendAudio", "video": "sendVideo", "voice": "sendVoice",
        }[kind]
        return await self.call(
            method, chat_id=chat_id,
            caption=(caption or "")[:TG_CAPTION_LIMIT] or None,
            reply_to_message_id=reply_to, allow_sending_without_reply=True,
            _files={kind: (filename, blob)},
        )

    async def edit_text(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self.call("editMessageText", chat_id=chat_id,
                            message_id=message_id, text=text[:TG_TEXT_LIMIT])
        except TelegramError as e:
            # у сообщения с медиа текста нет — правим подпись
            if "no text in the message" in e.description.lower():
                await self.call("editMessageCaption", chat_id=chat_id,
                                message_id=message_id,
                                caption=text[:TG_CAPTION_LIMIT])
            else:
                raise

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
