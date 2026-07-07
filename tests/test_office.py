"""Тесты сжатия OOXML (.pptx). Запуск: python -m unittest discover tests"""

import io
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

from pdfcompress.core import PRESETS
from pdfcompress.office import LegacyOfficeError, compress_office

SLIDE_XML = b'<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
CONTENT_TYPES = b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'


def _jpeg_bytes(w=3000, h=2000, quality=95) -> bytes:
    img = Image.effect_noise((w, h), 50).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _png_bytes(w=2500, h=2500) -> bytes:
    img = Image.effect_noise((w, h), 40).convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _make_pptx(path: str) -> dict:
    entries = {
        "[Content_Types].xml": CONTENT_TYPES,
        "ppt/slides/slide1.xml": SLIDE_XML,
        "ppt/media/image1.jpg": _jpeg_bytes(),
        "ppt/media/image2.png": _png_bytes(),
        "ppt/media/image3.gif": b"GIF89a" + b"\x00" * 5000,  # не перекодируется
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return entries


class OfficeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "deck.pptx")
        self.dst = os.path.join(self.tmp.name, "deck.out.pptx")
        self.entries = _make_pptx(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shrinks_and_keeps_structure(self):
        r = compress_office(self.src, self.dst, preset=PRESETS["ebook"])
        self.assertLess(r.output_bytes, r.input_bytes)
        self.assertEqual(r.images_total, 3)
        self.assertEqual(r.images_recompressed, 2)  # jpg + png; gif пропущен
        with zipfile.ZipFile(self.dst) as z:
            self.assertEqual(sorted(z.namelist()), sorted(self.entries))
            # не-медиа части байт-в-байт как в исходнике
            self.assertEqual(z.read("ppt/slides/slide1.xml"), SLIDE_XML)
            self.assertEqual(z.read("[Content_Types].xml"), CONTENT_TYPES)
            # форматы сохранены, размер ограничен пресетом
            jpg = Image.open(io.BytesIO(z.read("ppt/media/image1.jpg")))
            self.assertEqual(jpg.format, "JPEG")
            self.assertLessEqual(max(jpg.size), PRESETS["ebook"].max_dimension)
            png = Image.open(io.BytesIO(z.read("ppt/media/image2.png")))
            self.assertEqual(png.format, "PNG")
            self.assertEqual(png.mode, "RGBA")  # прозрачность не потеряна

    def test_lossless_keeps_media_bytes(self):
        compress_office(self.src, self.dst, preset=PRESETS["lossless"])
        with zipfile.ZipFile(self.dst) as z:
            for name, data in self.entries.items():
                self.assertEqual(z.read(name), data)

    def test_never_larger_than_input(self):
        mid = os.path.join(self.tmp.name, "mid.pptx")
        compress_office(self.src, mid, preset=PRESETS["screen"])
        r = compress_office(mid, self.dst, preset=PRESETS["screen"])
        self.assertLessEqual(r.output_bytes, r.input_bytes)

    def test_legacy_ppt_rejected(self):
        legacy = os.path.join(self.tmp.name, "old.ppt")
        with open(legacy, "wb") as f:
            f.write(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)  # сигнатура OLE
        with self.assertRaises(LegacyOfficeError):
            compress_office(legacy, self.dst)

    def test_cli_dispatches_pptx(self):
        from pdfcompress.cli import main

        out = os.path.join(self.tmp.name, "cli.pptx")
        self.assertEqual(main([self.src, "-o", out, "-p", "screen", "-q"]), 0)
        self.assertLess(os.path.getsize(out), os.path.getsize(self.src))

    def test_cli_legacy_ppt_fails_gracefully(self):
        from pdfcompress.cli import main

        legacy = os.path.join(self.tmp.name, "old.ppt")
        with open(legacy, "wb") as f:
            f.write(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
        self.assertEqual(main([legacy, "-q"]), 1)


if __name__ == "__main__":
    unittest.main()
