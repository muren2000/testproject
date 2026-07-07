@echo off
rem Сборка автономного приложения для Windows (не требует установленного Python у пользователя).
rem Запускать на Windows: scripts\build-windows.bat
rem Результат: dist\PDF Compress.exe (GUI) и dist\pdfcompress.exe (CLI).
setlocal
cd /d "%~dp0\.."

python -m venv .build-venv
call .build-venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

rem GUI-приложение (одним .exe, без окна консоли)
pyinstaller --noconfirm --onefile --windowed --name "PDF Compress" ^
  --collect-all pikepdf ^
  launcher_gui.py
if errorlevel 1 exit /b 1

rem CLI-утилита
pyinstaller --noconfirm --onefile --name pdfcompress ^
  --collect-all pikepdf ^
  launcher_cli.py
if errorlevel 1 exit /b 1

call .build-venv\Scripts\deactivate.bat
echo.
echo Готово:
echo   dist\"PDF Compress.exe"  — графическое приложение
echo   dist\pdfcompress.exe     — консольная утилита
endlocal
