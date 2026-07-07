"""Тесты ядра сжатия. Запуск: python -m unittest discover tests"""

import os
import random
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pikepdf
from pikepdf import Name, Pdf, PdfImage
from PIL import Image

from pdfcompress.core import PRESETS, compress_pdf


def _add_image_page(pdf: Pdf, image_dict: dict, raw: bytes) -> None:
    img = pdf.make_stream(raw)
    for k, v in image_dict.items():
        img[k] = v
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(
        XObject=pikepdf.Dictionary(Im0=pdf.make_indirect(img))
    )
    page.Contents = pdf.make_stream(b"q 612 0 0 792 0 0 cm /Im0 Do Q")


def _make_test_pdf(path: str, with_smask: bool = False) -> None:
    pdf = Pdf.new()
    pil = Image.effect_noise((1600, 2000), 40).convert("RGB")
    raw = zlib.compress(pil.tobytes())
    base = {
        Name.Type: Name.XObject,
        Name.Subtype: Name.Image,
        Name.Width: 1600,
        Name.Height: 2000,
        Name.ColorSpace: Name.DeviceRGB,
        Name.BitsPerComponent: 8,
        Name.Filter: Name.FlateDecode,
    }
    if with_smask:
        smask = pdf.make_stream(
            zlib.compress(Image.effect_noise((1600, 2000), 20).tobytes())
        )
        for k, v in {**base, Name.ColorSpace: Name.DeviceGray}.items():
            smask[k] = v
        base = {**base, Name.SMask: pdf.make_indirect(smask)}
    _add_image_page(pdf, base, raw)
    pdf.save(path)


def _verify_decodable(path: str, password: str = "") -> int:
    """Открывает PDF и декодирует все изображения; возвращает их число."""
    n = 0
    with pikepdf.open(path, password=password) as pdf:
        for page in pdf.pages:
            for _, obj in page.get_images().items():
                PdfImage(obj).as_pil_image()
                n += 1
    return n


class CompressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src.pdf")
        self.dst = os.path.join(self.tmp.name, "dst.pdf")

    def tearDown(self):
        self.tmp.cleanup()

    def test_shrinks_flate_image_pdf(self):
        _make_test_pdf(self.src)
        r = compress_pdf(self.src, self.dst, preset=PRESETS["ebook"])
        self.assertLess(r.output_bytes, r.input_bytes)
        self.assertEqual(r.images_recompressed, 1)
        self.assertEqual(_verify_decodable(self.dst), 1)

    def test_screen_smaller_than_print(self):
        _make_test_pdf(self.src)
        screen = os.path.join(self.tmp.name, "s.pdf")
        prnt = os.path.join(self.tmp.name, "p.pdf")
        compress_pdf(self.src, screen, preset=PRESETS["screen"])
        compress_pdf(self.src, prnt, preset=PRESETS["print"])
        self.assertLess(os.path.getsize(screen), os.path.getsize(prnt))

    def test_lossless_keeps_images_untouched(self):
        _make_test_pdf(self.src)
        r = compress_pdf(self.src, self.dst, preset=PRESETS["lossless"])
        self.assertEqual(r.images_recompressed, 0)
        self.assertEqual(_verify_decodable(self.dst), 1)

    def test_smask_preserved(self):
        _make_test_pdf(self.src, with_smask=True)
        compress_pdf(self.src, self.dst, preset=PRESETS["ebook"])
        with pikepdf.open(self.dst) as pdf:
            im = pdf.pages[0].Resources.XObject.Im0
            self.assertIn("/SMask", im)
            self.assertEqual(im.Filter, Name.DCTDecode)

    def test_never_larger_than_input(self):
        # Уже оптимальный PDF: результат не должен стать больше исходника.
        _make_test_pdf(self.src)
        mid = os.path.join(self.tmp.name, "mid.pdf")
        compress_pdf(self.src, mid, preset=PRESETS["screen"])
        r = compress_pdf(mid, self.dst, preset=PRESETS["screen"])
        self.assertLessEqual(r.output_bytes, r.input_bytes)

    def test_metadata_stripped_and_kept(self):
        _make_test_pdf(self.src)
        with pikepdf.open(self.src, allow_overwriting_input=True) as pdf:
            with pdf.open_metadata() as meta:
                meta["dc:title"] = "Секретный документ"
            pdf.save()
        compress_pdf(self.src, self.dst, strip_metadata=True)
        with pikepdf.open(self.dst) as pdf:
            with pdf.open_metadata() as meta:
                self.assertNotIn("dc:title", meta)
        kept = os.path.join(self.tmp.name, "kept.pdf")
        compress_pdf(self.src, kept, strip_metadata=False)
        with pikepdf.open(kept) as pdf:
            with pdf.open_metadata() as meta:
                self.assertEqual(meta.get("dc:title"), "Секретный документ")

    def test_encrypted_requires_password(self):
        _make_test_pdf(self.src)
        enc = os.path.join(self.tmp.name, "enc.pdf")
        with pikepdf.open(self.src) as pdf:
            pdf.save(enc, encryption=pikepdf.Encryption(owner="o", user="u"))
        with self.assertRaises(pikepdf.PasswordError):
            compress_pdf(enc, self.dst)
        r = compress_pdf(enc, self.dst, password="u")
        self.assertGreater(r.saved_percent, 0)
        self.assertEqual(_verify_decodable(self.dst), 1)


class CliTest(unittest.TestCase):
    def test_cli_end_to_end(self):
        from pdfcompress.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "doc.pdf")
            out = os.path.join(tmp, "out.pdf")
            _make_test_pdf(src)
            self.assertEqual(main([src, "-o", out, "-p", "screen", "-q"]), 0)
            self.assertTrue(os.path.getsize(out) < os.path.getsize(src))

    def test_cli_missing_file(self):
        from pdfcompress.cli import main

        self.assertEqual(main(["/nonexistent/x.pdf", "-q"]), 1)


if __name__ == "__main__":
    unittest.main()
