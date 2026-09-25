@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Не знайдено .venv — схоже, установку ще не робили.
    echo Спочатку запустіть install_windows.bat, потім спробуйте ще раз.
    pause
    exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tray_win.py"
