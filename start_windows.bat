@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"

rem Pure ASCII on purpose: Ukrainian text lives in install_messages.txt
rem (see the comment at the top of install_windows.bat for why).

if exist "%~dp0.venv\Scripts\pythonw.exe" goto run
for /f "tokens=1* delims=]" %%A in ('findstr /b /c:"[NOVENV" "%~dp0install_messages.txt"') do echo(%%B
pause
exit /b 1

:run
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tray_win.py"
