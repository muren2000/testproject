#!/bin/bash
# PDF Compress — запуск на macOS двойным щелчком.
# При первом запуске создаёт локальное окружение и ставит две библиотеки
# (нужен интернет один раз); дальше работает полностью офлайн.
set -e
cd "$(dirname "$0")"

pause_exit() {
  echo
  read -n 1 -s -r -p "Нажмите любую клавишу, чтобы закрыть окно…"
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден."
  echo "Установите его с https://www.python.org/downloads/ и запустите этот файл снова."
  pause_exit
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "В установленном Python нет модуля tkinter (нужен для окна программы)."
  echo "Установите Python с https://www.python.org/downloads/ — в нём tkinter есть."
  pause_exit
fi

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
  echo "Нужен Python 3.9 или новее. Обновите его с https://www.python.org/downloads/"
  pause_exit
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Первый запуск: настраиваю окружение (1–2 минуты, нужен интернет)…"
  python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install -r requirements.txt
  echo "Готово."
fi

exec ./.venv/bin/python -m pdfcompress --gui
