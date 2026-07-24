"""Точка входа: python -m bridge"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from .config import Config
from .idmap import IdMap
from .maxclient import MaxClient
from .relay import Bridge
from .tgclient import TelegramClient


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = Config.from_env()
    idmap = IdMap(cfg.db_path)

    # долгие таймауты нужны для long polling (timeout=30 на стороне API)
    timeout = aiohttp.ClientTimeout(total=90, connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        bridge = Bridge(
            cfg,
            TelegramClient(cfg.tg_token, session),
            MaxClient(cfg.max_token, session),
            idmap,
        )
        try:
            await bridge.run()
        finally:
            idmap.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
