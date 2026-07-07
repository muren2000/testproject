#!/usr/bin/env bash
# Сборка автономного приложения для macOS (не требует установленного Python у пользователя).
# Запускать на macOS: bash scripts/build-macos.sh
# Результат: dist/PDF Compress.app (GUI) и dist/pdfcompress (CLI).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

# GUI-приложение (.app, можно перетащить в /Applications)
pyinstaller --noconfirm --windowed --name "PDF Compress" \
  --osx-bundle-identifier com.pdfcompress.app \
  --collect-all pikepdf \
  launcher_gui.py

# CLI-бинарник
pyinstaller --noconfirm --onefile --name pdfcompress \
  --collect-all pikepdf \
  launcher_cli.py

deactivate
echo
echo "Готово:"
echo "  dist/PDF Compress.app  — графическое приложение"
echo "  dist/pdfcompress       — консольная утилита"
