"""Логика моста: два цикла long polling и пересылка событий между чатами."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from .config import Config
from .idmap import IdMap
from .maxclient import MaxClient, MaxError
from .tgclient import TelegramClient, TelegramError

log = logging.getLogger("bridge")

# тип вложения MAX -> метод отправки в Telegram
_MAX_TO_TG_KIND = {"image": "photo", "file": "document", "audio": "audio", "video": "video"}


class Bridge:
    def __init__(self, cfg: Config, tg: TelegramClient, mx: MaxClient, idmap: IdMap):
        self.cfg = cfg
        self.tg = tg
        self.mx = mx
        self.idmap = idmap
        self.tg_me: dict = {}
        self.max_me: dict = {}

    async def run(self) -> None:
        self.tg_me = await self.tg.get_me()
        self.max_me = await self.mx.get_me()
        log.info("Telegram-бот: @%s (id=%s)", self.tg_me.get("username"), self.tg_me.get("id"))
        log.info("MAX-бот: %s (user_id=%s)", self.max_me.get("name"), self.max_me.get("user_id"))

        if self.cfg.discovery_mode:
            log.warning(
                "TELEGRAM_CHAT_ID и/или MAX_CHAT_ID не заданы — режим обнаружения: "
                "добавьте ботов в нужные чаты и напишите там что-нибудь, "
                "chat_id появится в логе. Пересылка выключена."
            )

        await asyncio.gather(self._tg_loop(), self._max_loop())

    # ------------------------------------------------------------------
    # Telegram -> MAX
    # ------------------------------------------------------------------

    async def _tg_loop(self) -> None:
        async for upd in self.tg.updates(allowed=["message", "edited_message"]):
            try:
                await self._on_tg_update(upd)
            except (TelegramError, MaxError, aiohttp.ClientError) as e:
                log.error("Ошибка обработки события Telegram: %s", e)

    async def _on_tg_update(self, upd: dict) -> None:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]

        if self.cfg.discovery_mode:
            log.info("Telegram: сообщение в чате «%s», TELEGRAM_CHAT_ID=%s",
                     msg["chat"].get("title") or msg["chat"].get("username") or "личный чат",
                     chat_id)
            return

        if chat_id != self.cfg.tg_chat_id or self.cfg.direction == "max_to_tg":
            return
        sender = msg.get("from") or {}
        if sender.get("id") == self.tg_me.get("id"):
            return  # своё же сообщение — защита от зацикливания

        prefix = self._tg_author(sender)
        if "edited_message" in upd:
            await self._tg_edit_to_max(msg, prefix)
        else:
            await self._tg_new_to_max(msg, prefix)

    async def _tg_new_to_max(self, msg: dict, prefix: str) -> None:
        text = msg.get("text") or msg.get("caption") or ""
        attachment, kind_note = await self._tg_attachment_to_max(msg)

        reply_mid: Optional[str] = None
        reply = msg.get("reply_to_message")
        if reply:
            reply_mid = self.idmap.max_for_tg(reply["message_id"])

        body_text = self._compose(prefix, text, kind_note)
        if not body_text and not attachment:
            return  # сервисные события (вход в чат и т.п.) не пересылаем

        sent = await self.mx.send_message(
            self.cfg.max_chat_id, body_text,
            attachments=[attachment] if attachment else None,
            reply_to_mid=reply_mid,
        )
        mid = ((sent or {}).get("message") or {}).get("body", {}).get("mid")
        if mid:
            self.idmap.add(msg["message_id"], mid, origin="tg")

    async def _tg_edit_to_max(self, msg: dict, prefix: str) -> None:
        mid = self.idmap.max_for_tg(msg["message_id"])
        if not mid:
            return
        text = msg.get("text") or msg.get("caption") or ""
        await self.mx.edit_message(mid, self._compose(prefix, text, None))

    async def _tg_attachment_to_max(self, msg: dict) -> tuple[Optional[dict], Optional[str]]:
        """Возвращает (attachment для MAX, текстовая пометка-заглушка)."""
        try:
            if msg.get("photo"):
                largest = max(msg["photo"], key=lambda p: p.get("file_size") or 0)
                return await self._reupload_to_max("image", largest["file_id"]), None
            if msg.get("document"):
                return await self._reupload_to_max(
                    "file", msg["document"]["file_id"],
                    msg["document"].get("file_name")), None
            if msg.get("video"):
                return await self._reupload_to_max("video", msg["video"]["file_id"]), None
            if msg.get("video_note"):
                return await self._reupload_to_max("video", msg["video_note"]["file_id"]), None
            if msg.get("audio"):
                return await self._reupload_to_max(
                    "audio", msg["audio"]["file_id"],
                    msg["audio"].get("file_name")), None
            if msg.get("voice"):
                return await self._reupload_to_max("audio", msg["voice"]["file_id"]), None
        except (TelegramError, MaxError, aiohttp.ClientError) as e:
            log.error("Не удалось перенести вложение из Telegram: %s", e)
            return None, "[вложение не удалось переслать]"

        if msg.get("sticker"):
            emoji = (msg["sticker"].get("emoji") or "").strip()
            return None, f"[стикер {emoji}]".replace("  ", " ")
        for field, note in (("location", "[геометка]"), ("contact", "[контакт]"),
                            ("poll", "[опрос]"), ("animation", "[GIF]")):
            if msg.get(field):
                return None, note
        return None, None

    async def _reupload_to_max(self, upload_type: str, file_id: str,
                               filename: Optional[str] = None) -> dict:
        tg_name, blob = await self.tg.download_file(file_id)
        return await self.mx.upload(upload_type, filename or tg_name, blob)

    # ------------------------------------------------------------------
    # MAX -> Telegram
    # ------------------------------------------------------------------

    async def _max_loop(self) -> None:
        async for upd in self.mx.updates():
            try:
                await self._on_max_update(upd)
            except (TelegramError, MaxError, aiohttp.ClientError) as e:
                log.error("Ошибка обработки события MAX: %s", e)

    async def _on_max_update(self, upd: dict) -> None:
        utype = upd.get("update_type")

        if utype == "message_removed":
            await self._max_delete_to_tg(upd)
            return
        if utype not in ("message_created", "message_edited"):
            return

        msg = upd.get("message") or {}
        chat_id = (msg.get("recipient") or {}).get("chat_id")

        if self.cfg.discovery_mode:
            log.info("MAX: сообщение в чате, MAX_CHAT_ID=%s", chat_id)
            return

        if chat_id != self.cfg.max_chat_id or self.cfg.direction == "tg_to_max":
            return
        sender = msg.get("sender") or {}
        if sender.get("user_id") == self.max_me.get("user_id"):
            return  # защита от зацикливания

        prefix = self._max_author(sender)
        if utype == "message_edited":
            await self._max_edit_to_tg(msg, prefix)
        else:
            await self._max_new_to_tg(msg, prefix)

    async def _max_new_to_tg(self, msg: dict, prefix: str) -> None:
        body = msg.get("body") or {}
        text = body.get("text") or ""
        mid = body.get("mid")

        reply_to: Optional[int] = None
        linked = (msg.get("link") or {}).get("message") or {}
        if linked.get("mid"):
            reply_to = self.idmap.tg_for_max(linked["mid"])

        sent_ids: list[int] = []
        notes: list[str] = []
        media_sent = False

        for att in body.get("attachments") or []:
            att_type = att.get("type")
            kind = _MAX_TO_TG_KIND.get(att_type)
            payload = att.get("payload") or {}
            url = payload.get("url")
            if kind and url:
                try:
                    blob = await self.mx.download(url)
                    caption = self._compose(prefix, text, None) if not media_sent else None
                    sent = await self.tg.send_media(
                        self.cfg.tg_chat_id, kind,
                        att.get("filename") or f"attachment.{att_type}",
                        blob, caption=caption, reply_to=reply_to,
                    )
                    sent_ids.append(sent["message_id"])
                    media_sent = True
                    continue
                except (TelegramError, MaxError, aiohttp.ClientError) as e:
                    log.error("Не удалось перенести вложение из MAX: %s", e)
            if att_type == "sticker":
                notes.append("[стикер]")
            elif att_type not in (None, "share"):
                notes.append(f"[вложение: {att_type}]")

        # текст уже ушёл подписью к медиа — отдельным сообщением не дублируем
        if not media_sent:
            body_text = self._compose(prefix, text, " ".join(notes) or None)
            if body_text:
                sent = await self.tg.send_text(self.cfg.tg_chat_id, body_text,
                                               reply_to=reply_to)
                sent_ids.append(sent["message_id"])
        elif notes:
            sent = await self.tg.send_text(
                self.cfg.tg_chat_id, self._compose(prefix, "", " ".join(notes)))
            sent_ids.append(sent["message_id"])

        if mid:
            for tg_id in sent_ids:
                self.idmap.add(tg_id, mid, origin="max")

    async def _max_edit_to_tg(self, msg: dict, prefix: str) -> None:
        body = msg.get("body") or {}
        mid = body.get("mid")
        if not mid:
            return
        tg_id = self.idmap.tg_for_max(mid)
        if not tg_id:
            return
        await self.tg.edit_text(self.cfg.tg_chat_id, tg_id,
                                self._compose(prefix, body.get("text") or "", None))

    async def _max_delete_to_tg(self, upd: dict) -> None:
        if self.cfg.discovery_mode or self.cfg.direction == "tg_to_max":
            return
        if upd.get("chat_id") != self.cfg.max_chat_id:
            return
        tg_id = self.idmap.tg_for_max(upd.get("message_id") or "")
        if tg_id:
            try:
                await self.tg.delete_message(self.cfg.tg_chat_id, tg_id)
            except TelegramError as e:
                # Telegram не даёт удалять сообщения старше 48 часов
                log.warning("Не удалось удалить сообщение в Telegram: %s", e)

    # ------------------------------------------------------------------

    def _compose(self, prefix: str, text: str, note: Optional[str]) -> str:
        parts = [p for p in (text.strip(), (note or "").strip()) if p]
        combined = "\n".join(parts)
        if not combined:
            return ""
        return f"{prefix}{combined}"

    def _tg_author(self, sender: dict) -> str:
        if not self.cfg.show_author:
            return ""
        name = " ".join(filter(None, (sender.get("first_name"), sender.get("last_name")))) \
            or sender.get("username") or "?"
        return f"{name}:\n"

    def _max_author(self, sender: dict) -> str:
        if not self.cfg.show_author:
            return ""
        name = sender.get("name") or sender.get("username") or "?"
        return f"{name}:\n"
