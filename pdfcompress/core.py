"""Ядро сжатия PDF.

Стратегия:
1. Перекодирование растровых изображений: уменьшение разрешения до предела
   пресета и повторное сжатие в JPEG с заданным качеством.
2. Структурная оптимизация при сохранении: объектные потоки, пересжатие
   flate-потоков, удаление неиспользуемых объектов.
3. Опциональное удаление метаданных и миниатюр страниц.

Всё работает локально, без сети.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Callable, Optional

import pikepdf
from pikepdf import Name, Pdf, PdfError, PdfImage
from PIL import Image

# Изображения меньше этого размера (в байтах) не трогаем — выигрыш ничтожен.
MIN_IMAGE_BYTES = 4096

# Фильтры, которые уже дают компактный результат для 1-битных сканов.
SKIP_FILTERS = {"/CCITTFaxDecode", "/JBIG2Decode", "/JPXDecode"}


@dataclass(frozen=True)
class Preset:
    """Настройки уровня сжатия."""

    name: str
    description: str
    max_dimension: int  # предел длинной стороны изображения в пикселях (0 — без предела)
    jpeg_quality: int   # качество JPEG 1–95 (0 — не перекодировать изображения)


PRESETS: dict[str, Preset] = {
    "screen": Preset(
        name="screen",
        description="Максимальное сжатие: чтение с экрана (документы, e-mail)",
        max_dimension=1200,
        jpeg_quality=45,
    ),
    "ebook": Preset(
        name="ebook",
        description="Сильное сжатие: планшеты и электронные книги",
        max_dimension=1800,
        jpeg_quality=65,
    ),
    "print": Preset(
        name="print",
        description="Умеренное сжатие: пригодно для печати",
        max_dimension=2600,
        jpeg_quality=82,
    ),
    "lossless": Preset(
        name="lossless",
        description="Без потерь: только структурная оптимизация",
        max_dimension=0,
        jpeg_quality=0,
    ),
}


@dataclass
class CompressionResult:
    input_path: str
    output_path: str
    input_bytes: int
    output_bytes: int
    images_total: int
    images_recompressed: int

    @property
    def saved_bytes(self) -> int:
        return self.input_bytes - self.output_bytes

    @property
    def saved_percent(self) -> float:
        if self.input_bytes == 0:
            return 0.0
        return 100.0 * self.saved_bytes / self.input_bytes


ProgressFn = Callable[[int, int], None]


def _filters_of(obj: pikepdf.Object) -> set[str]:
    f = obj.get("/Filter")
    if f is None:
        return set()
    if isinstance(f, pikepdf.Array):
        return {str(x) for x in f}
    return {str(f)}


def _recompress_image(
    obj: pikepdf.Object, max_dimension: int, jpeg_quality: int
) -> bool:
    """Пробует перекодировать одно изображение. True — если заменили и стало меньше."""
    try:
        if obj.get("/Subtype") != Name.Image:
            return False
        if "/ImageMask" in obj and bool(obj.ImageMask):
            return False
        if _filters_of(obj) & SKIP_FILTERS:
            return False

        old_size = len(obj.read_raw_bytes())
        if old_size < MIN_IMAGE_BYTES:
            return False

        pil = PdfImage(obj).as_pil_image()
    except Exception:
        return False

    try:
        if pil.mode in ("1", "P", "PA", "RGBA", "LA", "CMYK", "I", "I;16", "F"):
            # Прозрачность в PDF живёт в /SMask, канал alpha тут лишний.
            pil = pil.convert("L" if pil.mode in ("1", "I", "I;16", "F") else "RGB")
        elif pil.mode not in ("L", "RGB"):
            pil = pil.convert("RGB")

        if max_dimension and max(pil.size) > max_dimension:
            pil.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        data = buf.getvalue()
        if len(data) >= old_size:
            return False

        obj.write(data, filter=Name.DCTDecode)
        obj.Width = pil.width
        obj.Height = pil.height
        obj.BitsPerComponent = 8
        obj.ColorSpace = Name.DeviceGray if pil.mode == "L" else Name.DeviceRGB
        # Устаревшие записи от старого кодирования.
        for key in ("/DecodeParms", "/Decode", "/Interpolate", "/Intent"):
            if key in obj:
                del obj[key]
        return True
    except Exception:
        return False


def _iter_page_images(pdf: Pdf):
    """Все image-XObject документа, каждый объект — один раз."""
    seen: set[tuple[int, int]] = set()
    for page in pdf.pages:
        try:
            # get_images() (pikepdf >= 9) находит и изображения внутри Form XObject.
            images = page.get_images() if hasattr(page, "get_images") else page.images
        except Exception:
            continue
        for _, obj in images.items():
            key = (obj.objgen[0], obj.objgen[1])
            if key in seen:
                continue
            seen.add(key)
            yield obj


def compress_pdf(
    input_path: str,
    output_path: str,
    preset: Preset = PRESETS["ebook"],
    strip_metadata: bool = True,
    password: str = "",
    progress: Optional[ProgressFn] = None,
) -> CompressionResult:
    """Сжимает PDF и пишет результат в output_path.

    Бросает pikepdf.PasswordError для зашифрованных файлов без пароля
    и pikepdf.PdfError для повреждённых файлов.
    """
    input_bytes = os.path.getsize(input_path)
    images_total = 0
    images_recompressed = 0

    with Pdf.open(input_path, password=password) as pdf:
        if preset.jpeg_quality > 0:
            targets = list(_iter_page_images(pdf))
            images_total = len(targets)
            for i, obj in enumerate(targets, 1):
                if _recompress_image(obj, preset.max_dimension, preset.jpeg_quality):
                    images_recompressed += 1
                if progress:
                    progress(i, images_total)

        for page in pdf.pages:
            if "/Thumb" in page:
                del page.Thumb

        if strip_metadata:
            if "/Metadata" in pdf.Root:
                del pdf.Root.Metadata
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                for k in list(meta.keys()):
                    del meta[k]
            try:
                del pdf.trailer.Info
            except (AttributeError, KeyError):
                pass

        pdf.remove_unreferenced_resources()
        pdf.save(
            output_path,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )

    output_bytes = os.path.getsize(output_path)

    # Если "сжатый" файл вышел больше исходного (уже оптимальный PDF) —
    # отдаём копию исходника.
    if output_bytes >= input_bytes:
        import shutil

        shutil.copyfile(input_path, output_path)
        output_bytes = input_bytes
        images_recompressed = 0

    return CompressionResult(
        input_path=input_path,
        output_path=output_path,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        images_total=images_total,
        images_recompressed=images_recompressed,
    )


def human_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024 or unit == "ГБ":
            return f"{n:.1f} {unit}" if unit != "Б" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} ГБ"
