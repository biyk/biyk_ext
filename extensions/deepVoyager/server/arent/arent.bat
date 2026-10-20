@echo off
rem arent\arent.bat - one wrapper for every arent command.
rem
rem   arent.bat info
rem   arent.bat gen --count 400
rem   arent.bat train --epochs 40
rem   arent.bat play --arena corridor_archer
rem
rem It prefers the built exe (dist\arent\arent.exe), then arent\.venv (the training env),
rem then the server\.venv next to it (dev machine: pure-python backend, no torch), and
rem last any bare python: gen / train / play / bench need no third-party packages at all
rem (verified on a venv created with --without-pip). Everything (data, runs) is resolved
rem relative to the folder the command runs from, so the same file works in the sources
rem and next to the exe.
setlocal
cd /d "%~dp0"

if exist "dist\arent\arent.exe" (
    "dist\arent\arent.exe" %*
    exit /b %errorlevel%
)

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" if exist "..\.venv\Scripts\python.exe" set "VPY=..\.venv\Scripts\python.exe"

if exist "%VPY%" (
    "%VPY%" main.py %*
    exit /b %errorlevel%
)

where py >nul 2>nul
if not errorlevel 1 (
    echo [arent] no venv here, using bare python - pure backend only, run setup.bat for torch
    py -3 main.py %*
    exit /b %errorlevel%
)

where python >nul 2>nul
if not errorlevel 1 (
    echo [arent] no venv here, using bare python - pure backend only, run setup.bat for torch
    python main.py %*
    exit /b %errorlevel%
)

echo [arent] nothing to run: no dist\arent\arent.exe, no .venv and no python on PATH
echo         install python 3.10+ or run setup.bat (it creates arent\.venv), then build_exe.bat
exit /b 1
