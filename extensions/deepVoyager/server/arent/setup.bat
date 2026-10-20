@echo off
rem arent\setup.bat - prepare the training environment INSIDE this folder (arent\.venv).
rem Run once on the machine with the RTX 4060, from the arent folder.
rem
rem   setup.bat            torch with CUDA 12.1 (needed to train on the GPU)  ~8 GB free
rem   setup.bat --cpu      torch cpu-only (small download, still much faster
rem                        than pure-python training)                          ~3 GB free
rem   setup.bat --lite     no torch at all, pure-python training only          ~1 GB free
rem   setup.bat --offline  torch from .whl files you copied into ..\wheels     ~3 GB free
rem
rem --offline is the answer to "no internet / disk full on this PC": download
rem   pip download torch --index-url https://download.pytorch.org/whl/cu121 -d wheels
rem on any other machine and copy the wheels folder next to arent (server\wheels).
setlocal enableextensions
rem (no enabledelayedexpansion: nothing here uses !var!, and it would make any stray "!"
rem  or ")" inside a parenthesized echo abort the script - the exact bug that gave exit 255.)
cd /d "%~dp0"

set "MODE=cuda"
if "%~1"=="--cpu" set "MODE=cpu"
if "%~1"=="--lite" set "MODE=lite"
if "%~1"=="--offline" set "MODE=offline"

set "BASE=python"
where py >nul 2>nul
if not errorlevel 1 set "BASE=py -3"

echo [setup] interpreter: %BASE%
%BASE% -V
if errorlevel 1 goto :fail

rem --- disk preflight: the CUDA wheel is 2.4 GB and pip unpacks another ~5 GB.
rem The check runs on THIS drive, where this folder (and so .venv) really lives.
set "NEED_GB=8"
if "%MODE%"=="cpu" set "NEED_GB=3"
if "%MODE%"=="offline" set "NEED_GB=3"
if "%MODE%"=="lite" set "NEED_GB=1"
for /f "delims=" %%i in ('%BASE% -c "import shutil;print(int(shutil.disk_usage('.').free/1073741824))"') do set "FREE_GB=%%i"
echo [setup] mode %MODE%, need %NEED_GB% GB free on this drive, %FREE_GB% GB free here.
for /f "delims=" %%i in ('%BASE% -c "print(1 if %FREE_GB% >= %NEED_GB% else 0)"') do set "ENOUGH=%%i"
if not "%ENOUGH%"=="1" goto :nospace

rem --- pip builds and caches on %TEMP%, which is usually on C: even when this
rem folder lives on D:. Point it here instead, or a full C: kills the install.
if not exist ".pip-tmp" mkdir ".pip-tmp"
set "TMP=%~dp0.pip-tmp"
set "TEMP=%~dp0.pip-tmp"
set "TMPDIR=%~dp0.pip-tmp"

if not exist ".venv\" (
    echo [setup] creating arent\.venv ...
    %BASE% -m venv .venv
    if errorlevel 1 goto :fail
)
set "VPY=.venv\Scripts\python.exe"

echo [setup] upgrading pip / setuptools / wheel (failure here is not fatal) ...
"%VPY%" -m pip install --retries 8 --timeout 60 --upgrade pip setuptools wheel
if errorlevel 1 echo [setup] warning: pip bootstrap did not finish; the torch step below still works via --extra-index-url.

if "%MODE%"=="lite" goto :tools

rem torch is PINNED to 2.5.1+cu121 so the --extra-index-url below can never make pip
rem pull a newer, non-CUDA torch off PyPI (PyPI newest would outrank 2.5.1+cu121).
rem --extra-index-url https://pypi.org/simple is REQUIRED, not optional: a freshly created
rem venv ships an old pip whose wheel-name check rejects the PyTorch "typing_extensions"
rem WHEEL ("inconsistent Name: expected 'typing-extensions', metadata has 'typing_extensions'")
rem and falls back to building that package from a .tar.gz. Building it needs the backend
rem flit_core, which is NOT on the PyTorch index - so without PyPI the install dies with
rem "No matching distribution found for flit_core" even though torch itself downloaded fine.
set "PIPArgs=install --no-cache-dir --retries 8 --timeout 120"
if "%MODE%"=="cuda" set "PIPArgs=%PIPArgs% torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 --extra-index-url https://pypi.org/simple"
if "%MODE%"=="cpu" set "PIPArgs=%PIPArgs% torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"
if "%MODE%"=="offline" set "PIPArgs=install --no-cache-dir --no-index --find-links ..\wheels torch"

echo [setup] installing torch (%MODE%) ...
"%VPY%" -m pip %PIPArgs%
if errorlevel 1 goto :fail

rem torch prints "Failed to initialize NumPy" without numpy; our code never uses it, so
rem this is cosmetic only - install it to keep the console clean, and never in --offline
rem (that mode assumes no internet). Failure here is not fatal.
rem NOTE: this must NOT be a parenthesized ( ... ) block. With enabledelayedexpansion an
rem echo line containing a ")" closes the block early and cmd then prints
rem "... was unexpected at this time." and aborts the whole setup right after torch.
rem That is exactly the exit 255 seen on the 4060, so this uses a goto instead.
if "%MODE%"=="offline" goto :tools
echo [setup] installing numpy to silence a harmless torch import warning ...
"%VPY%" -m pip install --no-cache-dir --retries 5 --timeout 120 numpy
if errorlevel 1 echo [setup] warning: numpy not installed, torch will still print the warning.

:tools
echo [setup] installing pyinstaller ...
"%VPY%" -m pip install --retries 5 --timeout 60 -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [setup] what arent sees now - check the cuda line:
"%VPY%" main.py info
if errorlevel 1 goto :fail
echo [setup] if "cuda" is false while you asked for the GPU build, the driver is
echo         missing or older than CUDA 12.1 - run "nvidia-smi" and compare.
echo.
echo [setup] done. next: build_exe.bat, then arent.bat gen / train / bench / play
endlocal
exit /b 0

:nospace
echo [setup] NOT ENOUGH SPACE: %MODE% needs about %NEED_GB% GB free, this drive has %FREE_GB% GB.
echo         Options:
echo          1. copy the whole deepVoyager/server folder to a drive with space and rerun.
echo          2. setup.bat --lite   - no download at all, trains pure-python on CPU.
echo          3. setup.bat --cpu    - about 200 MB download, still ~13x faster than --lite.
echo          4. setup.bat --offline - copy torch .whl files into server\wheels from another PC.
pause
endlocal
exit /b 1

:fail
echo [setup] FAILED. Read the lines above. Check that python 3.10+ is installed and that
echo         the arent folder was copied completely (main.py must be next to this file).
pause
endlocal
exit /b 1
