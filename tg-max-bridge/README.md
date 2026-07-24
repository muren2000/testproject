# tg-max-bridge — свой мост Telegram ↔ MAX

Self-hosted аналог сервисов «синхронизации Telegram и MAX»: бот-мост, который
пересылает сообщения между группой в Telegram и чатом в MAX **в обе стороны**,
включая медиа, правки и удаления.

Зачем свой? Сторонний бот-мост читает *всю* переписку в обоих чатах и хранит
её на чужом сервере. Здесь весь код — ~600 строк на Python с одной зависимостью
(`aiohttp`), токены и сообщения не покидают вашу машину.

## Возможности

| Что | TG → MAX | MAX → TG |
|---|---|---|
| Текст (с именем автора) | ✅ | ✅ |
| Фото, файлы, видео, аудио, голосовые | ✅ | ✅ |
| Ответы (reply) | ✅ | ✅ |
| Правки сообщений | ✅ (текст) | ✅ (текст) |
| Удаления | ❌ * | ✅ |
| Стикеры, геометки, опросы | текстовая заглушка | текстовая заглушка |

\* Ограничение самого Telegram Bot API: ботам не приходят события об
удалении сообщений, поэтому удаление в Telegram отследить невозможно.

## Установка

Нужен Python 3.10+.

```bash
cd tg-max-bridge
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 1. Создайте ботов

* **Telegram** — напишите [@BotFather](https://t.me/BotFather): `/newbot`,
  скопируйте токен в `TELEGRAM_BOT_TOKEN`.
  Затем обязательно `/setprivacy` → выберите бота → **Disable**, иначе бот
  не будет видеть обычные сообщения в группе.
* **MAX** — напишите боту `@masterbot` в MAX (документация: [dev.max.ru](https://dev.max.ru)),
  создайте бота и скопируйте токен в `MAX_BOT_TOKEN`.

### 2. Добавьте ботов в чаты

Добавьте Telegram-бота в вашу группу, MAX-бота — в ваш чат MAX
(в MAX боту может понадобиться право отправки сообщений — выдайте его при добавлении).

### 3. Узнайте ID чатов

Запустите мост с пустыми `TELEGRAM_CHAT_ID` / `MAX_CHAT_ID`:

```bash
python -m bridge
```

Напишите любое сообщение в каждом из чатов — ID появятся в логе:

```
INFO bridge: Telegram: сообщение в чате «Моя группа», TELEGRAM_CHAT_ID=-1001234567890
INFO bridge: MAX: сообщение в чате, MAX_CHAT_ID=987654321
```

Впишите их в `.env` и перезапустите. Всё, мост работает.

## Запуск как сервис (systemd)

`/etc/systemd/system/tg-max-bridge.service`:

```ini
[Unit]
Description=Telegram <-> MAX bridge
After=network-online.target

[Service]
WorkingDirectory=/opt/tg-max-bridge
ExecStart=/opt/tg-max-bridge/.venv/bin/python -m bridge
Restart=always
RestartSec=5
User=bridge

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now tg-max-bridge
```

## Как это устроено

* `bridge/tgclient.py` — тонкий клиент [Telegram Bot API](https://core.telegram.org/bots/api)
  (long polling `getUpdates`).
* `bridge/maxclient.py` — тонкий клиент [MAX Bot API](https://dev.max.ru)
  (long polling `GET /updates` с маркером; протокол сверен с официальной
  библиотекой [max-botapi-python](https://github.com/max-messenger/max-botapi-python)).
* `bridge/relay.py` — пересылка: скачивает вложение из одного мессенджера,
  загружает в другой; правки и удаления синхронизируются через локальную
  SQLite-базу соответствий id сообщений (`bridge.sqlite3`).
* Защита от зацикливания: мост игнорирует сообщения, отправленные его же ботами.

## Тесты

```bash
python -m unittest discover tests -v
```

## Ограничения

* Одна пара чатов на процесс (для нескольких пар запустите несколько
  экземпляров с разными `.env` через `BRIDGE_ENV_FILE`).
* Правка синхронизирует только текст, замена медиа не переносится.
* Форматирование (жирный, ссылки) переносится как обычный текст.
* MAX ограничивает бота 30 запросами в секунду — для личных чатов это
  заведомо достаточно.
