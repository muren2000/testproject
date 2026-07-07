"""Графический интерфейс на tkinter (входит в стандартный Python на macOS и Windows)."""

from __future__ import annotations

import os
import queue
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover
    print(
        "Не найден tkinter. На Windows/macOS он входит в установщик Python с python.org;\n"
        "в Linux установите пакет python3-tk (например: sudo apt install python3-tk).",
        file=sys.stderr,
    )
    sys.exit(1)

import pikepdf

from . import __version__
from .core import PRESETS, compress_pdf, human_size


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"PDF Compress {__version__} — офлайн-сжатие PDF")
        self.geometry("640x480")
        self.minsize(560, 420)

        self.files: list[str] = []
        self.preset_var = tk.StringVar(value="ebook")
        self.keep_meta_var = tk.BooleanVar(value=False)
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 5}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Добавить PDF…", command=self._add_files).pack(side="left")
        ttk.Button(top, text="Очистить список", command=self._clear_files).pack(
            side="left", padx=8
        )

        self.listbox = tk.Listbox(self, height=8)
        self.listbox.pack(fill="both", expand=True, **pad)

        presets = ttk.LabelFrame(self, text="Уровень сжатия")
        presets.pack(fill="x", **pad)
        for key in ("screen", "ebook", "print", "lossless"):
            p = PRESETS[key]
            ttk.Radiobutton(
                presets,
                text=f"{key} — {p.description}",
                value=key,
                variable=self.preset_var,
            ).pack(anchor="w", padx=8, pady=2)

        ttk.Checkbutton(
            self, text="Сохранить метаданные документа", variable=self.keep_meta_var
        ).pack(anchor="w", **pad)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)

        self.status = ttk.Label(self, text="Добавьте PDF-файлы и нажмите «Сжать».")
        self.status.pack(fill="x", **pad)

        self.compress_btn = ttk.Button(self, text="Сжать", command=self._start)
        self.compress_btn.pack(pady=10)

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Выберите PDF-файлы", filetypes=[("PDF", "*.pdf"), ("Все файлы", "*.*")]
        )
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", p)

    def _clear_files(self) -> None:
        self.files.clear()
        self.listbox.delete(0, "end")

    def _start(self) -> None:
        if not self.files:
            messagebox.showinfo("PDF Compress", "Сначала добавьте хотя бы один PDF-файл.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.compress_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(self.files))
        files = list(self.files)
        preset = PRESETS[self.preset_var.get()]
        keep_meta = self.keep_meta_var.get()
        self.worker = threading.Thread(
            target=self._run, args=(files, preset, keep_meta), daemon=True
        )
        self.worker.start()

    def _run(self, files: list[str], preset, keep_meta: bool) -> None:
        lines: list[str] = []
        for i, path in enumerate(files, 1):
            self.msg_queue.put(("status", f"Сжатие {i}/{len(files)}: {os.path.basename(path)}…"))
            base, ext = os.path.splitext(path)
            out = f"{base}.compressed{ext or '.pdf'}"
            try:
                r = compress_pdf(path, out, preset=preset, strip_metadata=not keep_meta)
                lines.append(
                    f"{os.path.basename(path)}: {human_size(r.input_bytes)} -> "
                    f"{human_size(r.output_bytes)} (-{r.saved_percent:.0f}%)"
                )
            except pikepdf.PasswordError:
                lines.append(f"{os.path.basename(path)}: пропущен (зашифрован паролем)")
            except Exception as e:
                lines.append(f"{os.path.basename(path)}: ошибка — {e}")
            self.msg_queue.put(("progress", i))
        self.msg_queue.put(("done", "\n".join(lines)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status":
                    self.status.config(text=payload)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "done":
                    self.compress_btn.config(state="normal")
                    self.status.config(text="Готово. Файлы *.compressed.pdf лежат рядом с исходниками.")
                    messagebox.showinfo("PDF Compress — готово", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
