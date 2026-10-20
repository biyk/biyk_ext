@echo off
rem AB.bat - the one-click decisive A/B for the long-horizon roadmap (Phase 0).
rem
rem   NOTE: AUTO.bat already runs this whole A/B automatically as its STEP 4, so you do NOT
rem   need to launch AB.bat yourself. Open AB.bat directly only to repeat JUST the experiment
rem   without rebuilding the venv or retraining bc2.
rem
rem   Prerequisite: run AUTO.bat first, so the GPU venv exists next to AB.bat. Then
rem   double-click this file. It does the experiment the whole roadmap has been waiting for:
rem   it labels the SAME battle states twice - identical count and seed - and changes ONLY
rem   the teacher horizon:
rem       arm A = teacher-rounds 1  (greedy, shallow one-move labels - the old behaviour)
rem       arm B = teacher-rounds 2  (one lookahead step deeper - the long-horizon labels)
rem   Then it trains BOTH and lets BOTH play every fight all the way through with
rem   `arent evaluate`, so the comparison is the OUTCOME (survival rate / clear rate /
rem   accumulated value), not just the single-move val.joint that hid the real effect.
rem
rem   What comes back: ab-back.zip sitting next to AB.bat. It carries abA_summary.json,
rem   abB_summary.json, abA_eval.json, abB_eval.json plus every step log, so the difference
rem   between shallow and deep teacher labels can be read straight off the eval reports.
rem
rem   Device agnostic on purpose: with the AUTO.bat venv present the trains use CUDA
rem   automatically; without one it warns and still runs on pure python, so the whole flow
rem   is testable on any machine. gen (the teacher) is always CPU-bound.
rem
rem   Optional positional overrides, blank keeps the default:
rem       AB.bat [count] [epochs] [rounds] [seed] [--no-live]
rem       e.g.   AB.bat 800 200 8 7
setlocal enableextensions
cd /d "%~dp0"

set "ABLOG=%~dp0ab.log"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

set "COUNT=600"
set "EPOCHS=200"
set "ROUNDS=8"
set "SEED=7"
set "LIVEFLAG="
if not "%~1"=="" set "COUNT=%~1"
if not "%~2"=="" set "EPOCHS=%~2"
if not "%~3"=="" set "ROUNDS=%~3"
if not "%~4"=="" set "SEED=%~4"
if /i "%~5"=="--no-live" set "LIVEFLAG=--no-live"

> "%ABLOG%" echo AB.bat run start %DATE% %TIME%  cwd=%CD%  count=%COUNT% epochs=%EPOCHS% rounds=%ROUNDS% seed=%SEED%

set "ARENT="
if exist "server\arent\main.py" set "ARENT=server\arent"
if not defined ARENT if exist "arent\main.py" set "ARENT=arent"
if not defined ARENT if exist "main.py" set "ARENT=."
if not defined ARENT (
    call :log "FATAL - arent folder not found next to AB.bat - unpack the WHOLE archive and run AB.bat from its root"
    echo [ab] I cannot find the arent folder. Run AB.bat from the archive root, next to server\.
    if not defined ARENT_CALLED pause
    exit /b 1
)

set "HELPER=%~dp0%ARENT%\pack\run_logged.ps1"
set "VPY=%ARENT%\.venv\Scripts\python.exe"
set "RUNDIR=%ARENT%\runs"
set "ARENTBAT=%~dp0%ARENT%\arent.bat"
set "CAPS=%~dp0%ARENT%\data\payloads\captures"

rem AUTO.bat owns the torch/CUDA build. If its venv is here the arms train on it; if not we
rem only warn (gen/train/evaluate all still run on pure python) so nothing here can hang.
"%VPY%" -c "import torch" 1>nul 2>nul
if errorlevel 1 goto :no_torch
call :log "torch venv found - both arms will train on it (CUDA on the 4060)"
goto :env_ready

:no_torch
call :log "WARNING no torch venv - run AUTO.bat first for the 4060 path; continuing on pure python (CPU, slower)"

:env_ready
rem The bundled playground arenas yield only a handful of learnable states, so a meaningful
rem A/B needs live captures (js_arena.js saves them into data\payloads\captures). Say so loudly.
dir /b "%CAPS%\*.json" 1>nul 2>nul
if errorlevel 1 call :log "NOTE no live captures in data\payloads\captures - A/B runs on bundled arenas only, a few states, weak signal by design"

call :log "info snapshot saved to ab-info.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "info" -Log "%~dp0ab-info.txt"

call :log "ARM A gen abA teacher-rounds 1 count=%COUNT% seed=%SEED%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "gen --name abA --count %COUNT% --teacher-rounds 1 --seed %SEED% %LIVEFLAG%" -Log "%~dp0genA.log"
set "GRC=%errorlevel%"
call :log "ARM A gen done exit=%GRC% - detail in genA.log"
if not "%GRC%"=="0" goto :fail

call :log "ARM A train abA epochs=%EPOCHS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "train --dataset abA --name abA --epochs %EPOCHS%" -Log "%~dp0trainA.log"
set "TRC=%errorlevel%"
call :log "ARM A train done exit=%TRC% - detail in trainA.log"
if not "%TRC%"=="0" goto :fail

call :log "ARM A evaluate abA rounds=%ROUNDS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "evaluate --model abA --name eval_abA --rounds %ROUNDS% %LIVEFLAG%" -Log "%~dp0abA_eval.log"
set "ERC=%errorlevel%"
call :log "ARM A evaluate done exit=%ERC% - detail in abA_eval.log"
if not "%ERC%"=="0" goto :fail

call :log "ARM B gen abB teacher-rounds 2 count=%COUNT% seed=%SEED%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "gen --name abB --count %COUNT% --teacher-rounds 2 --seed %SEED% %LIVEFLAG%" -Log "%~dp0genB.log"
set "GRC=%errorlevel%"
call :log "ARM B gen done exit=%GRC% - detail in genB.log"
if not "%GRC%"=="0" goto :fail

call :log "ARM B train abB epochs=%EPOCHS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "train --dataset abB --name abB --epochs %EPOCHS%" -Log "%~dp0trainB.log"
set "TRC=%errorlevel%"
call :log "ARM B train done exit=%TRC% - detail in trainB.log"
if not "%TRC%"=="0" goto :fail

call :log "ARM B evaluate abB rounds=%ROUNDS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%ARENTBAT%" -Arg "evaluate --model abB --name eval_abB --rounds %ROUNDS% %LIVEFLAG%" -Log "%~dp0abB_eval.log"
set "ERC=%errorlevel%"
call :log "ARM B evaluate done exit=%ERC% - detail in abB_eval.log"
if not "%ERC%"=="0" goto :fail

call :log "packing ab-back.zip"
set "ABOUT=%~dp0ab-back"
set "ABZIP=%~dp0ab-back.zip"
if exist "%ABOUT%" rmdir /s /q "%ABOUT%"
mkdir "%ABOUT%" 1>nul 2>nul
copy /y "%RUNDIR%\abA\summary.json"   "%ABOUT%\abA_summary.json" 1>nul 2>nul
copy /y "%RUNDIR%\abB\summary.json"   "%ABOUT%\abB_summary.json" 1>nul 2>nul
copy /y "%RUNDIR%\eval_abA\eval.json" "%ABOUT%\abA_eval.json"    1>nul 2>nul
copy /y "%RUNDIR%\eval_abB\eval.json" "%ABOUT%\abB_eval.json"    1>nul 2>nul
if exist "%~dp0ab-info.txt"  copy /y "%~dp0ab-info.txt"  "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0genA.log"     copy /y "%~dp0genA.log"     "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0trainA.log"   copy /y "%~dp0trainA.log"   "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0abA_eval.log" copy /y "%~dp0abA_eval.log" "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0genB.log"     copy /y "%~dp0genB.log"     "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0trainB.log"   copy /y "%~dp0trainB.log"   "%ABOUT%\" 1>nul 2>nul
if exist "%~dp0abB_eval.log" copy /y "%~dp0abB_eval.log" "%ABOUT%\" 1>nul 2>nul
if exist "%ABLOG%"           copy /y "%ABLOG%"           "%ABOUT%\" 1>nul 2>nul
if exist "%ABZIP%" del /q "%ABZIP%"
powershell -NoProfile -Command "Compress-Archive -Force -DestinationPath '%ABZIP%' -Path '%ABOUT%\*'"
if errorlevel 1 (
    call :log "FAILED to build ab-back.zip"
    if not defined ARENT_CALLED pause
    exit /b 1
)

call :log "DONE - send ab-back.zip and ab.log"
if not defined ARENT_CALLED (
    echo.
    echo [ab] DONE. Read the two eval files side by side: abA_eval.json vs abB_eval.json.
    echo      If arm B survives more and clears more, the deeper teacher labels helped.
    echo [ab] Send me  %ABZIP%  and  %ABLOG%  - both sit next to AB.bat.
    pause
)
exit /b 0

:fail
call :log "AB stopped early - the step that failed is the last marker above; ab-back.zip NOT packed"
if not defined ARENT_CALLED (
    echo [ab] A step failed. Send me  ab.log  and the last genA / trainA / abA_eval / genB log.
    pause
)
exit /b 1

:log
rem One timestamped marker per step, flushed to ab.log immediately and mirrored to the screen.
>>"%ABLOG%" echo %DATE% %TIME% - %~1
echo [%TIME%] [ab] %~1
exit /b 0
