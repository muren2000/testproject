"""Простое нативное окно на tkinter (входит в стандартный Python на macOS и Windows)."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, ttk
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
from .office import (
    LegacyOfficeError,
    compress_office,
    is_legacy_office_file,
    is_office_file,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"PDF Compress {__version__}")
        self.geometry("780x520")
        self.minsize(700, 460)

        self.rows: dict[str, str] = {}  # путь -> id строки таблицы
        self.preset_var = tk.StringVar(value="ebook")
        self.keep_meta_var = tk.BooleanVar(value=False)
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Добавить файлы…", command=self._add_files).pack(side="left")
        ttk.Button(top, text="Очистить", command=self._clear_files).pack(side="left", padx=8)
        ttk.Label(
            top, text="Результат сохраняется рядом с исходником: имя.compressed.*"
        ).pack(side="left", padx=8)

        cols = ("size", "result", "saved", "reveal")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", height=8)
        self.tree.heading("#0", text="Файл")
        self.tree.heading("size", text="Было")
        self.tree.heading("result", text="Стало")
        self.tree.heading("saved", text="Экономия")
        self.tree.heading("reveal", text="")
        self.tree.column("#0", width=250, anchor="w")
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("result", width=100, anchor="e")
        self.tree.column("saved", width=80, anchor="e")
        self.tree.column("reveal", width=130, anchor="center", stretch=False)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.pack(fill="both", expand=True, **pad)

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

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        ttk.Checkbutton(
            opts, text="Сохранить метаданные документа", variable=self.keep_meta_var
        ).pack(side="left")

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.compress_btn = ttk.Button(bottom, text="Сжать", command=self._start)
        self.compress_btn.pack(side="left")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        self.status = ttk.Label(self, text="Добавьте файлы (PDF, PPTX, DOCX, XLSX) и нажмите «Сжать».")
        self.status.pack(fill="x", padx=12, pady=(0, 10))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Выберите файлы",
            filetypes=[
                ("PDF и презентации", "*.pdf *.pptx *.docx *.xlsx"),
                ("PDF", "*.pdf"),
                ("PowerPoint", "*.pptx"),
                ("Word / Excel", "*.docx *.xlsx"),
                ("Все файлы", "*.*"),
            ],
        )
        for p in paths:
            self.add_file(p)

    def add_file(self, path: str) -> None:
        if path in self.rows:
            return
        size = human_size(os.path.getsize(path)) if os.path.exists(path) else "?"
        item = self.tree.insert(
            "", "end", text=os.path.basename(path),
            values=(size, "", "", "Показать в папке"),
        )
        self.rows[path] = item

    @staticmethod
    def _output_for(path: str) -> str:
        base, ext = os.path.splitext(path)
        return f"{base}.compressed{ext or '.pdf'}"

    def _on_tree_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#4":  # колонка «Показать в папке»
            return
        item = self.tree.identify_row(event.y)
        for path, it in self.rows.items():
            if it == item:
                out = self._output_for(path)
                self._reveal(out if os.path.exists(out) else path)
                break

    @staticmethod
    def _reveal(path: str) -> None:
        """Открывает системный файловый менеджер с выделенным файлом."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            elif os.name == "nt":
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
        except OSError:
            pass

    def _clear_files(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.status.config(text="Добавьте файлы (PDF, PPTX, DOCX, XLSX) и нажмите «Сжать».")
        self.progress.config(value=0)

    def _start(self) -> None:
        if not self.rows:
            self.status.config(text="Сначала добавьте хотя бы один файл.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.compress_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(self.rows))
        jobs = dict(self.rows)
        preset = PRESETS[self.preset_var.get()]
        keep_meta = self.keep_meta_var.get()
        self.worker = threading.Thread(
            target=self._run, args=(jobs, preset, keep_meta), daemon=True
        )
        self.worker.start()

    def _run(self, jobs: dict[str, str], preset, keep_meta: bool) -> None:
        done = failed = 0
        for i, (path, item) in enumerate(jobs.items(), 1):
            name = os.path.basename(path)
            self.msg_queue.put(("status", f"Сжатие {i}/{len(jobs)}: {name}…"))
            base, ext = os.path.splitext(path)
            out = f"{base}.compressed{ext or '.pdf'}"
            try:
                if is_office_file(path) or is_legacy_office_file(path):
                    r = compress_office(path, out, preset=preset)
                else:
                    r = compress_pdf(path, out, preset=preset, strip_metadata=not keep_meta)
                self.msg_queue.put(
                    ("row", (item, human_size(r.output_bytes), f"−{r.saved_percent:.0f}%"))
                )
                done += 1
            except LegacyOfficeError:
                self.msg_queue.put(("row", (item, "пересохраните как .pptx", "—")))
                failed += 1
            except pikepdf.PasswordError:
                self.msg_queue.put(("row", (item, "зашифрован", "—")))
                failed += 1
            except Exception:
                self.msg_queue.put(("row", (item, "ошибка", "—")))
                failed += 1
            self.msg_queue.put(("progress", i))
        summary = f"Готово: {done} из {len(jobs)}."
        if failed:
            summary += f" С ошибкой: {failed}."
        summary += " Файлы *.compressed.* лежат рядом с исходниками."
        self.msg_queue.put(("done", summary))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "status":
                    self.status.config(text=payload)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "row":
                    item, result, saved = payload
                    if self.tree.exists(item):
                        self.tree.set(item, "result", result)
                        self.tree.set(item, "saved", saved)
                elif kind == "done":
                    self.compress_btn.config(state="normal")
                    self.status.config(text=payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
