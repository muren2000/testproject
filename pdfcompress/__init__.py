"""pdfcompress — офлайн-сжатие PDF и офисных файлов для macOS и Windows."""

__version__ = "1.2.0"

from .core import CompressionResult, Preset, PRESETS, compress_pdf
from .office import LegacyOfficeError, compress_office

__all__ = [
    "CompressionResult",
    "Preset",
    "PRESETS",
    "compress_pdf",
    "compress_office",
    "LegacyOfficeError",
    "__version__",
]
