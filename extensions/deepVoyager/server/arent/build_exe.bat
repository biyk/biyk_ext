@echo off
rem arent\build_exe.bat - build dist\arent\arent.exe (PyInstaller, one-dir).
rem
rem Needs setup.bat run before (arent\.venv) AND the parent server\ folder next to
rem arent\ - the teacher (planner) and the arenas (playground) are bundled from there,
rem without them the exe could only play, not train.
setlocal
cd /d "%~dp0"

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo [build] no arent\.venv - run setup.bat first
    exit /b 1
)
if not exist "..\planner\" (
    echo [build] no ..\planner - copy the whole server folder, not arent\ alone
    exit /b 1
)

echo [build] pyinstaller --clean arent.spec ...
"%VPY%" -m PyInstaller --noconfirm --clean arent.spec
if errorlevel 1 (
    echo [build] FAILED - read the log above
    pause
    exit /b 1
)

rem data lives next to the exe: data\ and runs\ must be visible without _internal
if not exist "dist\arent\data\payloads\" mkdir "dist\arent\data\payloads"
copy /y "data\payloads\*.json" "dist\arent\data\payloads\" >nul
copy /y "config.json" "dist\arent\config.json" >nul
rem coefficients of the teacher: the exe reads points.json from next to itself (main.py)
if exist "..\points.json" copy /y "..\points.json" "dist\arent\points.json" >nul

echo [build] ok: dist\arent\arent.exe
"dist\arent\arent.exe" info
exit /b %errorlevel%
