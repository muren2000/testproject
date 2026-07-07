"""pdfcompress — офлайн-инструмент сжатия PDF для macOS и Windows."""

__version__ = "1.0.0"

from .core import CompressionResult, Preset, PRESETS, compress_pdf

__all__ = ["CompressionResult", "Preset", "PRESETS", "compress_pdf", "__version__"]
