@echo off
rem RUN_ALL.bat - one click, nothing to type: environment + benchmark + training.
rem
rem Double-click it from the unpacked folder. It does everything on its own:
rem   1. builds server\arent\.venv (torch) only if it is not built yet
rem   2. adds numpy so torch stops printing the "No module named numpy" warning
rem   3. arent bench  - measures pure vs torch+cpu vs torch+cuda on THIS box (RTX 4060)
rem   4. arent train  - trains a real model; it ALWAYS saves best + last checkpoint
rem Each long step runs through pack\run_logged.ps1: its output is shown LIVE and saved to a
rem file at once (setup.log / bench.log / train.log), so even if the window dies mid-run the
rem real last lines survive. run.log gets ONE flushed marker per step the instant it starts,
rem so a "frozen" window is never silent and the LAST line shows where it broke. If a step
rem fails it stops with a non-zero code, so a broken run never prints the "done" summary.
rem Re-run any time: when the environment already exists it skips step 1. Flags go to
rem setup.bat on the FIRST run only:  RUN_ALL.bat --cpu | --lite | --offline
setlocal enableextensions
cd /d "%~dp0"

set "RUNLOG=%~dp0run.log"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

rem Backend the operator asked for (default cuda = the 4060 build); drives the GPU gate below.
set "MODE=cuda"
if "%~1"=="--cpu" set "MODE=cpu"
if "%~1"=="--lite" set "MODE=lite"
if "%~1"=="--offline" set "MODE=offline"

> "%RUNLOG%" echo RUN_ALL.bat run start %DATE% %TIME%  cwd=%CD%
echo [run] live step log :  %RUNLOG%   (a marker line per step as it starts)
echo [run] stage output  :  setup.log / bench.log / info.txt - shown live AND saved to file
echo.

if not exist "server\arent\main.py" (
    call :log "FATAL - server\arent missing, unpack the archive completely first"
    echo [run] server\arent is missing - unpack the archive completely first.
    pause
    exit /b 1
)

set "ARENT=server\arent"
set "HELPER=%~dp0%ARENT%\pack\run_logged.ps1"
set "VPY=%ARENT%\.venv\Scripts\python.exe"
set "BC2=%ARENT%\runs\bc2"
set "BENCH=%ARENT%\runs\bench\bench.json"
set "TRAINLOG=%BC2%\train.log"
set "INFO=%~dp0info.txt"
set "BENCHLOG=%~dp0bench.log"
set "SETUPLOG=%~dp0setup.log"

call :log "STEP 1/3 - environment, mode=%MODE%"
rem Reuse an existing venv only when it really has the requested backend: a stale or --lite
rem venv would otherwise train on pure-python while the operator thinks the 4060 is used.
if not exist "%VPY%" goto :build_env
if "%MODE%"=="lite" goto :have_env
"%VPY%" -c "import torch" 1>nul 2>nul
if errorlevel 1 goto :build_env
goto :have_env

:build_env
call :log "STEP 1 creating .venv + torch - live AND saved to setup.log; up to ~2.4 GB, 5-20 min; on space fail retry RUN_ALL.bat --cpu / --lite / --offline"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\setup.bat" -Arg "%*" -Log "%SETUPLOG%"
set "SRC=%errorlevel%"
call :log "STEP 1 setup.bat returned code=%SRC% - detail in setup.log"
if "%SRC%"=="0" goto :env_ready
call :log "STEP 1 FAILED - setup (see setup.log and START_HERE.txt)"
pause
exit /b 1

:have_env
call :log "STEP 1 reusing existing venv - backend check passed - python = %VPY%"

:env_ready
call :log "STEP 1 done - venv python = %VPY%"
rem Loud gate: asked for GPU but CUDA not usable -> stop, do not fake a run on pure-python.
if not "%MODE%"=="cuda" goto :numpy_step
"%VPY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 1>nul 2>nul
if not errorlevel 1 goto :cuda_ok
call :log "STEP 1 GPU GATE FAILED - mode=cuda but torch.cuda.is_available is false"
echo [run] The 4060 is NOT usable: torch installed but CUDA off - check the driver with nvidia-smi.
echo [run] To proceed on CPU now:  RUN_ALL.bat --cpu   or   RUN_ALL.bat --lite
pause
exit /b 1
:cuda_ok
call :log "STEP 1 GPU GATE OK - CUDA is visible, torch will train on the 4060"
:numpy_step
rem cosmetic, non-fatal: torch warns without numpy; our code never needs it
if exist "%VPY%" "%VPY%" -c "import numpy" 1>nul 2>nul
if errorlevel 1 "%VPY%" -m pip install --no-cache-dir --retries 5 --timeout 120 numpy 1>nul 2>nul

call :log "STEP 2/3 - arent info then benchmark (GPU vs CPU)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "info" -Log "%INFO%"
set "IRC=%errorlevel%"
call :log "STEP 2 info done exit=%IRC% - detail in info.txt"
rem Fallback: if the tee helper left info.txt absent, capture the backend report directly.
if not exist "%INFO%" call "%~dp0%ARENT%\arent.bat" info > "%INFO%" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "bench --epochs 5" -Log "%BENCHLOG%"
set "BRC=%errorlevel%"
call :log "STEP 2 bench done exit=%BRC% - detail in bench.log"
if not "%BRC%"=="0" (
    call :log "STEP 2 FAILED - benchmark before any training"
    pause
    exit /b 1
)

call :log "STEP 3/3 - training bc2 from bc1 (best and last always saved). LONG step: watch train.log grow."
rem Fresh-run guard: remove any previous bc2 so old files can't be mistaken for this run.
if exist "%BC2%" rmdir /s /q "%BC2%"
mkdir "%BC2%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "train --dataset bc1 --warm bc1 --name bc2 --epochs 200" -Log "%TRAINLOG%"
set "TRC=%errorlevel%"
call :log "STEP 3 train done exit=%TRC% - full log in train.log"
if not "%TRC%"=="0" (
    call :log "STEP 3 FAILED - training (see train.log and run.log)"
    pause
    exit /b 1
)

call :log "checking that every required artifact exists and is not empty"
set "FAIL="
for %%F in (
    "%BC2%\model.json"
    "%BC2%\model_best.json"
    "%BC2%\summary.json"
    "%BC2%\history.json"
    "%BENCH%"
) do (
    if not exist %%F (
        echo [run] MISSING   %%~F
        set "FAIL=1"
    ) else (
        for %%A in (%%F) do if %%~zA LSS 1 (
            echo [run] EMPTY     %%~F
            set "FAIL=1"
        )
    )
)
if defined FAIL (
    call :log "ARTIFACT CHECK FAILED - run.log has the step markers"
    pause
    exit /b 1
)

call :log "DONE - exit 0"
echo.
echo [run] done. Where the results are:
echo   run.log                                 - live step markers (send it if anything broke)
echo   server\arent\runs\bench\bench.json      - GPU vs CPU timing (send this file back)
echo   server\arent\runs\bc2\model_best.json   - best epoch (by val.joint) - this is the model
echo   server\arent\runs\bc2\model.json        - last epoch
echo   server\arent\runs\bc2\summary.json      - metrics and which epoch won
echo   server\arent\runs\bc2\train.log         - full training log
echo   bench.log info.txt setup.log (here)     - timing + what arent sees + install log
echo.
echo To play one move with the new model:
echo   server\arent\arent.bat play --model bc2 --payload data\payloads\arena1_live.json
pause
exit /b 0

:log
rem Append one timestamped marker to run.log and flush it immediately, then mirror to screen.
>>"%RUNLOG%" echo %DATE% %TIME% - %~1
echo [%TIME%] [run] %~1
exit /b 0
