"""Командная строка: pdfcompress input.pdf [-o output.pdf] [--preset ebook]"""

from __future__ import annotations

import argparse
import os
import sys

import zipfile

import pikepdf

from . import __version__
from .core import PRESETS, compress_pdf, human_size
from .office import (
    LegacyOfficeError,
    compress_office,
    is_legacy_office_file,
    is_office_file,
)


def _default_output(input_path: str) -> str:
    base, ext = os.path.splitext(input_path)
    return f"{base}.compressed{ext or '.pdf'}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfcompress",
        description="Офлайн-сжатие PDF и офисных файлов (.pptx/.docx/.xlsx) "
        "на macOS / Windows / Linux.",
        epilog="Пресеты: "
        + "; ".join(f"{k} — {v.description}" for k, v in PRESETS.items()),
    )
    p.add_argument(
        "inputs", nargs="+", metavar="INPUT",
        help="исходные файлы: .pdf, .pptx, .docx, .xlsx",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT.pdf",
        help="куда сохранить результат (только для одного входного файла; "
        "по умолчанию рядом с исходником: NAME.compressed.pdf)",
    )
    p.add_argument(
        "-p",
        "--preset",
        choices=sorted(PRESETS),
        default="ebook",
        help="уровень сжатия (по умолчанию: ebook)",
    )
    p.add_argument(
        "--keep-metadata",
        action="store_true",
        help="не удалять метаданные документа",
    )
    p.add_argument("--password", default="", help="пароль зашифрованного PDF")
    p.add_argument("-q", "--quiet", action="store_true", help="печатать только ошибки")
    p.add_argument("--version", action="version", version=f"pdfcompress {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.output and len(args.inputs) > 1:
        print("Ошибка: -o/--output нельзя использовать с несколькими файлами.", file=sys.stderr)
        return 2

    preset = PRESETS[args.preset]
    failures = 0

    for input_path in args.inputs:
        if not os.path.isfile(input_path):
            print(f"Ошибка: файл не найден: {input_path}", file=sys.stderr)
            failures += 1
            continue

        output_path = args.output or _default_output(input_path)
        try:
            if is_office_file(input_path) or is_legacy_office_file(input_path):
                result = compress_office(input_path, output_path, preset=preset)
            else:
                result = compress_pdf(
                    input_path,
                    output_path,
                    preset=preset,
                    strip_metadata=not args.keep_metadata,
                    password=args.password,
                )
        except (LegacyOfficeError, zipfile.BadZipFile) as e:
            print(f"Ошибка: {input_path}: {e}", file=sys.stderr)
            failures += 1
            continue
        except pikepdf.PasswordError:
            print(
                f"Ошибка: {input_path} зашифрован — укажите пароль через --password.",
                file=sys.stderr,
            )
            failures += 1
            continue
        except pikepdf.PdfError as e:
            print(f"Ошибка: не удалось обработать {input_path}: {e}", file=sys.stderr)
            failures += 1
            continue

        if not args.quiet:
            print(
                f"{input_path}: {human_size(result.input_bytes)} -> "
                f"{human_size(result.output_bytes)} "
                f"(-{result.saved_percent:.1f}%, изображений перекодировано: "
                f"{result.images_recompressed}/{result.images_total})\n"
                f"  Сохранено в: {result.output_path}"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
