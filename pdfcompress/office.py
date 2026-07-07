"""Сжатие офисных OOXML-файлов: .pptx (а также .docx, .xlsx).

OOXML-файл — это ZIP-архив; изображения лежат в ppt/media/ (word/media/,
xl/media/). Стратегия та же, что и для PDF: уменьшение разрешения и
пересжатие изображений, плюс переупаковка архива с максимальным deflate.

Формат каждого изображения сохраняется (JPEG остаётся JPEG, PNG — PNG):
имена файлов и связи (rels) внутри архива не меняются, поэтому документ
остаётся полностью валидным.

Старый бинарный формат .ppt/.doc/.xls не поддерживается — его нельзя
безопасно перепаковать без Microsoft Office; файл нужно пересохранить
в современном формате (.pptx и т.п.).
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from typing import Optional

from PIL import Image

from .core import MIN_IMAGE_BYTES, PRESETS, CompressionResult, Preset, ProgressFn

MEDIA_DIRS = ("ppt/media/", "word/media/", "xl/media/")
OFFICE_EXTS = {".pptx", ".ppsx", ".potx", ".docx", ".xlsx"}
LEGACY_EXTS = {".ppt", ".pps", ".pot", ".doc", ".xls"}


class LegacyOfficeError(ValueError):
    """Старый бинарный формат Office (до 2007), перепаковка невозможна."""


def _recompress_media(name: str, data: bytes, preset: Preset) -> Optional[bytes]:
    """Пересжимает одно изображение из media. None — оставить как есть."""
    ext = os.path.splitext(name)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg") or len(data) < MIN_IMAGE_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    if getattr(img, "is_animated", False):
        return None

    fmt = img.format  # исходный формат сохраняем — имена и rels не меняются
    if preset.max_dimension and max(img.size) > preset.max_dimension:
        img.thumbnail((preset.max_dimension, preset.max_dimension), Image.LANCZOS)

    buf = io.BytesIO()
    try:
        if fmt == "JPEG":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(buf, "JPEG", quality=preset.jpeg_quality, optimize=True)
        elif fmt == "PNG":
            img.save(buf, "PNG", optimize=True)
        else:
            return None
    except Exception:
        return None

    out = buf.getvalue()
    return out if len(out) < len(data) else None


def compress_office(
    input_path: str,
    output_path: str,
    preset: Preset = PRESETS["ebook"],
    progress: Optional[ProgressFn] = None,
) -> CompressionResult:
    """Сжимает .pptx/.docx/.xlsx и пишет результат в output_path."""
    ext = os.path.splitext(input_path)[1].lower()
    if ext in LEGACY_EXTS:
        raise LegacyOfficeError(
            f"формат {ext} (старый бинарный Office) не поддерживается — "
            f"откройте файл и пересохраните его как {ext}x"
        )

    input_bytes = os.path.getsize(input_path)
    images_total = 0
    images_recompressed = 0

    with zipfile.ZipFile(input_path) as zin:
        entries = zin.infolist()
        media_names = [
            e.filename
            for e in entries
            if e.filename.startswith(MEDIA_DIRS)
        ]
        with zipfile.ZipFile(
            output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zout:
            done = 0
            for entry in entries:
                data = zin.read(entry.filename)
                if preset.jpeg_quality > 0 and entry.filename in media_names:
                    images_total += 1
                    new = _recompress_media(entry.filename, data, preset)
                    if new is not None:
                        data = new
                        images_recompressed += 1
                    done += 1
                    if progress:
                        progress(done, len(media_names))
                zout.writestr(entry.filename, data)

    output_bytes = os.path.getsize(output_path)
    if output_bytes >= input_bytes:
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


def is_office_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in OFFICE_EXTS


def is_legacy_office_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in LEGACY_EXTS
