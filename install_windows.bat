@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem All Ukrainian text lives in install_messages.txt and is printed via
rem the :say / :getmsg helpers below (findstr + for /f), never via a
rem literal echo "..." with Cyrillic text typed directly in this file.
rem Reason (found by testing on a real Windows 11 box): cmd.exe under
rem codepage 65001 corrupts its OWN batch parsing the moment it has to
rem tokenize a non-ASCII byte written directly in a command line in this
rem file (echo/set/if/rem argument, even a comment) - one bad multi-byte
rem read desyncs cmd's read position for the rest of the file, so later
rem PURE ASCII lines start failing too ("... is not recognized as an
rem internal or external command"). Text read from an external UTF-8
rem file via findstr/for-f and printed with echo(%%B is not affected,
rem because cmd never has to parse that text as batch syntax - it is
rem passed through as opaque data. So: keep this file itself pure ASCII,
rem put every user-facing Ukrainian string in install_messages.txt.

set "MSGFILE=%~dp0install_messages.txt"

set "PROJDIR=%~dp0"
if "%PROJDIR:~-1%"=="\" set "PROJDIR=%PROJDIR:~0,-1%"

echo ============================================================
call :say TITLE
echo ============================================================
echo %PROJDIR%
echo.

rem --- 1. Find Python ---------------------------------------------------
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYCMD=py -3"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=python"
    )
)

if "%PYCMD%"=="" (
    call :say NOPY1
    echo.
    call :say NOPY2
    call :say NOPY3
    call :say NOPY4
    call :say NOPY5
    call :say NOPY6
    call :say NOPY7
    echo.
    pause
    exit /b 1
)

%PYCMD% --version

rem --- 2. Create .venv if missing -----------------------------------------
if exist "%PROJDIR%\.venv\Scripts\python.exe" (
    call :say VENVHAVE
) else (
    call :say VENVNEW
    %PYCMD% -m venv "%PROJDIR%\.venv"
    if errorlevel 1 (
        echo.
        call :say VENVFAIL
        pause
        exit /b 1
    )
)

rem --- 3. Install dependencies ---------------------------------------------
echo.
call :say DEPSGO
"%PROJDIR%\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "%PROJDIR%\requirements-windows.txt"
if errorlevel 1 (
    echo.
    call :say DEPSFAIL
    pause
    exit /b 1
)
call :say DEPSOK

rem --- 4. Desktop shortcut ---------------------------------------------------
echo.
call :say SCGO

call :getmsg SHORTCUTNAME SHORTCUTNAME
set "PYTHONWPATH=%PROJDIR%\.venv\Scripts\pythonw.exe"
set "TARGETSCRIPT=%PROJDIR%\tray_win.py"
set "ICONPATH=%PROJDIR%\CityRadar.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $ws=New-Object -ComObject WScript.Shell; $desktop=$ws.SpecialFolders('Desktop'); $lnk=$ws.CreateShortcut((Join-Path $desktop $env:SHORTCUTNAME)); $lnk.TargetPath=$env:PYTHONWPATH; $lnk.Arguments=$q+$env:TARGETSCRIPT+$q; $lnk.WorkingDirectory=$env:PROJDIR; $lnk.IconLocation=$env:ICONPATH; $lnk.Save()"
if errorlevel 1 (
    call :say SCFAIL
) else (
    call :say SCOK
    echo %UserProfile%\Desktop\%SHORTCUTNAME%
)

rem --- 5. Autostart (optional) ------------------------------------------------
echo.
call :getmsg STARTQ STARTQTEXT
choice /C YN /M "%STARTQTEXT%"
set "WANTSTARTUP=%errorlevel%"
if "%WANTSTARTUP%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $ws=New-Object -ComObject WScript.Shell; $startup=[Environment]::GetFolderPath('Startup'); $lnk=$ws.CreateShortcut((Join-Path $startup $env:SHORTCUTNAME)); $lnk.TargetPath=$env:PYTHONWPATH; $lnk.Arguments=$q+$env:TARGETSCRIPT+$q; $lnk.WorkingDirectory=$env:PROJDIR; $lnk.IconLocation=$env:ICONPATH; $lnk.Save()"
    if errorlevel 1 (
        call :say STARTFAIL
    ) else (
        call :say STARTOK
    )
)

rem --- 6. What's next -------------------------------------------------------
echo.
echo ============================================================
call :say DONEHDR
echo ============================================================
echo.
call :say DONE01
call :say DONE02
call :say DONE03
call :say DONE04
echo.
call :say DONE05
call :say DONE06
echo       "%PROJDIR%\.venv\Scripts\python.exe" auth.py
echo.
call :say DONE07
call :say DONE08
echo.
call :say DONE09
call :say DONE10
call :say DONE11
call :say DONE12
echo.
pause
exit /b 0

rem ============================================================
rem  Helpers - print Ukrainian text stored in install_messages.txt.
rem  See the comment block at the top of this file for why.
rem ============================================================
:say
for /f "tokens=1* delims=]" %%A in ('findstr /b /c:"[%~1]" "%MSGFILE%"') do echo(%%B
goto :eof

:getmsg
for /f "tokens=1* delims=]" %%A in ('findstr /b /c:"[%~1]" "%MSGFILE%"') do set "%~2=%%B"
goto :eof
