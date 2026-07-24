"""Офлайн-тесты: конфиг, база соответствий, сборка текста."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.config import Config, load_dotenv, _int_or_none
from bridge.idmap import IdMap
from bridge.relay import Bridge


class ConfigTest(unittest.TestCase):
    def setUp(self):
        for key in ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                    "MAX_CHAT_ID", "BRIDGE_DIRECTION"):
            os.environ.pop(key, None)

    def test_missing_tokens_exit(self):
        os.environ["BRIDGE_ENV_FILE"] = "/nonexistent"
        with self.assertRaises(SystemExit):
            Config.from_env()

    def test_discovery_mode(self):
        cfg = Config(tg_token="t", max_token="m", tg_chat_id=None, max_chat_id=5)
        self.assertTrue(cfg.discovery_mode)
        cfg = Config(tg_token="t", max_token="m", tg_chat_id=-100, max_chat_id=5)
        self.assertFalse(cfg.discovery_mode)

    def test_int_or_none(self):
        self.assertIsNone(_int_or_none(""))
        self.assertIsNone(_int_or_none(None))
        self.assertEqual(_int_or_none("-100123"), -100123)
        with self.assertRaises(SystemExit):
            _int_or_none("abc")

    def test_load_dotenv(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# комментарий\nFOO_TEST_KEY=bar\nQUOTED_TEST_KEY='baz'\n")
            path = f.name
        try:
            os.environ.pop("FOO_TEST_KEY", None)
            load_dotenv(path)
            self.assertEqual(os.environ["FOO_TEST_KEY"], "bar")
            self.assertEqual(os.environ["QUOTED_TEST_KEY"], "baz")
        finally:
            os.unlink(path)
            os.environ.pop("FOO_TEST_KEY", None)
            os.environ.pop("QUOTED_TEST_KEY", None)


class IdMapTest(unittest.TestCase):
    def test_roundtrip(self):
        m = IdMap(":memory:")
        m.add(42, "mid.abc", origin="tg")
        self.assertEqual(m.max_for_tg(42), "mid.abc")
        self.assertEqual(m.tg_for_max("mid.abc"), 42)
        self.assertIsNone(m.max_for_tg(999))
        self.assertIsNone(m.tg_for_max("nope"))
        m.close()

    def test_latest_wins(self):
        m = IdMap(":memory:")
        m.add(1, "old", origin="max")
        m.add(1, "new", origin="max")
        self.assertEqual(m.max_for_tg(1), "new")
        m.close()


class ComposeTest(unittest.TestCase):
    def _bridge(self, show_author=True):
        cfg = Config(tg_token="t", max_token="m", tg_chat_id=1, max_chat_id=2,
                     show_author=show_author)
        return Bridge(cfg, tg=None, mx=None, idmap=None)

    def test_compose_with_prefix(self):
        b = self._bridge()
        self.assertEqual(b._compose("Вася:\n", "привет", None), "Вася:\nпривет")
        self.assertEqual(b._compose("Вася:\n", "", "[стикер]"), "Вася:\n[стикер]")
        self.assertEqual(b._compose("Вася:\n", "", None), "")

    def test_author_names(self):
        b = self._bridge()
        self.assertEqual(b._tg_author({"first_name": "Иван", "last_name": "Петров"}),
                         "Иван Петров:\n")
        self.assertEqual(b._tg_author({"username": "ivan"}), "ivan:\n")
        self.assertEqual(b._max_author({"name": "Мария"}), "Мария:\n")
        self.assertEqual(b._max_author({}), "?:\n")

    def test_author_disabled(self):
        b = self._bridge(show_author=False)
        self.assertEqual(b._tg_author({"first_name": "Иван"}), "")
        self.assertEqual(b._compose("", "привет", None), "привет")


if __name__ == "__main__":
    unittest.main()
