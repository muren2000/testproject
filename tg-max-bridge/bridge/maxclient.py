"""Тонкий клиент Bot API мессенджера MAX (https://dev.max.ru).

Протокол сверен с официальной библиотекой max-messenger/max-botapi-python:
  * база: https://botapi.max.ru, авторизация query-параметром access_token;
  * GET  /updates?marker=&limit=&timeout=  -> {"updates": [...], "marker": N}
  * POST /messages?chat_id=  тело {"text", "attachments", "link", "notify"}
  * PUT  /messages?message_id=<mid>  — правка;  DELETE /messages?message_id=
  * POST /uploads?type=image|video|audio|file -> {"url", "token"?},
    затем multipart-POST поля "data" на выданный url.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

import aiohttp

log = logging.getLogger("bridge.max")

MAX_TEXT_LIMIT = 4000
BASE_URL = "https://botapi.max.ru"


class MaxError(Exception):
    def __init__(self, code: int, raw: Any):
        super().__init__(f"[{code}] {raw}")
        self.code = code
        self.raw = raw if isinstance(raw, dict) else {}


class MaxClient:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self._token = token
        self._session = session

    async def call(self, http_method: str, path: str,
                   params: Optional[dict[str, Any]] = None,
                   body: Optional[dict[str, Any]] = None) -> Any:
        query = {"access_token": self._token}
        if params:
            query.update({k: v for k, v in params.items() if v is not None})
        resp = await self._session.request(
            http_method, f"{BASE_URL}{path}", params=query, json=body,
        )
        if resp.status == 401:
            raise SystemExit("MAX: неверный токен бота (401)")
        raw = await resp.json(content_type=None)
        if resp.status >= 400:
            raise MaxError(resp.status, raw)
        return raw

    async def get_me(self) -> dict:
        return await self.call("GET", "/me")

    async def updates(self) -> AsyncIterator[dict]:
        """Бесконечный long polling /updates c маркером продолжения."""
        marker: Optional[int] = None
        while True:
            try:
                batch = await self.call(
                    "GET", "/updates",
                    params={"marker": marker, "limit": 100, "timeout": 30},
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("MAX /updates: %s — повтор через 3 с", e)
                await asyncio.sleep(3)
                continue
            except MaxError as e:
                log.error("MAX /updates: %s — повтор через 5 с", e)
                await asyncio.sleep(5)
                continue
            marker = batch.get("marker", marker)
            for upd in batch.get("updates", []):
                yield upd

    # --- вложения ---

    async def upload(self, upload_type: str, filename: str, blob: bytes) -> dict:
        """Загружает файл и возвращает готовый attachment для /messages.

        upload_type: image | video | audio | file
        """
        target = await self.call("POST", "/uploads", params={"type": upload_type})
        form = aiohttp.FormData()
        form.add_field("data", blob, filename=filename)
        async with self._session.post(target["url"], data=form) as resp:
            resp.raise_for_status()
            upload_response = await resp.text()

        # источник токена зависит от типа: у video/audio он приходит сразу
        # в ответе /uploads, у image/file — в теле ответа сервера загрузки
        if upload_type in ("video", "audio"):
            token = target.get("token")
        elif upload_type == "file":
            token = json.loads(upload_response)["token"]
        else:  # image
            photos = json.loads(upload_response)["photos"]
            token = next(iter(photos.values()))["token"]
        if not token:
            raise MaxError(0, {"error": "upload: сервер не вернул token"})
        return {"type": upload_type, "payload": {"token": token}}

    async def download(self, url: str) -> bytes:
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

    # --- сообщения ---

    async def send_message(self, chat_id: int, text: Optional[str],
                           attachments: Optional[list[dict]] = None,
                           reply_to_mid: Optional[str] = None) -> dict:
        body: dict[str, Any] = {
            "text": (text or "")[:MAX_TEXT_LIMIT] or None,
            "attachments": attachments or [],
            "notify": True,
        }
        if reply_to_mid:
            body["link"] = {"type": "reply", "mid": reply_to_mid}

        # только что загруженное вложение может быть ещё не обработано —
        # API отвечает attachment.not.ready, повторяем с паузой
        for attempt in range(5):
            try:
                return await self.call("POST", "/messages",
                                       params={"chat_id": chat_id}, body=body)
            except MaxError as e:
                if e.raw.get("code") == "attachment.not.ready" and attempt < 4:
                    log.info("MAX: вложение ещё обрабатывается, попытка %d", attempt + 2)
                    await asyncio.sleep(2)
                    continue
                raise
        raise AssertionError("unreachable")

    async def edit_message(self, mid: str, text: str) -> None:
        await self.call("PUT", "/messages", params={"message_id": mid},
                        body={"text": text[:MAX_TEXT_LIMIT]})

    async def delete_message(self, mid: str) -> None:
        await self.call("DELETE", "/messages", params={"message_id": mid})
