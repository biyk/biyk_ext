@echo off
rem AUTO.bat - the ONLY file you need to run.
rem
rem   1. unpack the WHOLE archive into one folder (do not copy single files out of it)
rem   2. double-click this AUTO.bat (it sits next to the "server" folder inside the archive)
rem   3. send back what appears next to AUTO.bat:
rem        always   -> auto.log   (a live marker per step: the LAST line shows where it broke)
rem        success  -> results-back.zip   (models + every log)  AND  ab-back.zip (the A/B)
rem        failure  -> logs-back.zip      (captured logs, no models)
rem        and the raw stage logs next to AUTO.bat: setup.log / bench.log / info.txt
rem   AUTO.bat now runs the WHOLE roadmap in one go: env -> bench -> STEP 3a gen (grow the
rem   dataset on top of the bundled bc1) -> train bc2 on that bigger set (warm bc1) -> evaluate
rem   -> pack results -> the long-horizon A/B (delegated to AB.bat) -> pack ab-back.zip. One
rem   click and it never waits for a keypress - no "Press any key" anywhere, it just runs to
rem   the end and closes. If the window vanishes before you read it, everything is still in
rem   auto.log (open it in Notepad or any text editor) and inside the output zips. If the A/B
rem   step fails the main results are already safe in results-back.zip.
rem
rem Why the long steps are now safe: each one runs through pack\run_logged.ps1, which shows
rem its output LIVE on the screen AND writes it to a file at the same time. So even if the
rem window dies in the middle (e.g. during the torch download), the file keeps the real last
rem lines. auto.log also gets ONE flushed marker line the instant every step starts, so a
rem "frozen" window is never silent. Training ALWAYS saves best + last epoch (no --keep-best
rem flag). On any failed step it stops with a non-zero code and never fakes success. Flags
rem matter only on the first run (tight disk):  AUTO.bat --cpu  or  AUTO.bat --lite
setlocal enableextensions
cd /d "%~dp0"

set "AUTOLOG=%~dp0auto.log"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

rem Which backend the operator asked for drives the GPU gate below. Default is cuda (the
rem 4060 build). --cpu / --lite / --offline are passed straight through to setup.bat.
set "MODE=cuda"
if "%~1"=="--cpu" set "MODE=cpu"
if "%~1"=="--lite" set "MODE=lite"
if "%~1"=="--offline" set "MODE=offline"

> "%AUTOLOG%" echo AUTO.bat run start %DATE% %TIME%  cwd=%CD%
echo [auto] live step log :  %AUTOLOG%   (a marker line is written for every step as it starts)
echo [auto] stage output  :  setup.log / bench.log / info.txt - shown live AND saved to file
echo.

set "ARENT="
if exist "server\arent\main.py" set "ARENT=server\arent"
if not defined ARENT if exist "arent\main.py" set "ARENT=arent"
if not defined ARENT if exist "main.py" set "ARENT=."
if not defined ARENT (
    call :log "FATAL - arent folder not found next to AUTO.bat"
    echo [auto] I cannot find the arent folder next to this file.
    echo        Unpack the ENTIRE archive somewhere, then run the AUTO.bat that is
    echo        inside it. The folder you run from must contain a "server" subfolder.
    exit /b 1
)

set "HELPER=%~dp0%ARENT%\pack\run_logged.ps1"
set "VPY=%ARENT%\.venv\Scripts\python.exe"
set "RUNDIR=%ARENT%\runs"
set "BC2=%RUNDIR%\bc2"
set "BENCH=%RUNDIR%\bench\bench.json"
set "TRAINLOG=%BC2%\train.log"
set "INFO=%~dp0info.txt"
set "BENCHLOG=%~dp0bench.log"
set "SETUPLOG=%~dp0setup.log"
set "OUT=%~dp0results-back"
set "ZIP=%~dp0results-back.zip"
set "SAMPLES=%ARENT%\data\samples"
set "BC1DS=%SAMPLES%\bc1.jsonl"
set "BCALL=%SAMPLES%\bcall.jsonl"
set "GENLOG=%~dp0gen.log"
set "BC2MAN=%BC2%\run_manifest.json"

rem Kill console QuickEdit for this window: a stray click used to freeze all stdout (the
rem run looked dead, CPU/GPU idle) until an Enter. Non-interactive now cannot be stalled.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%ARENT%\pack\no_quickedit.ps1" 1>nul 2>nul

call :log "STEP 1 of 3 - environment, mode=%MODE%"
rem Reusing a venv is only safe when it really contains the requested backend: a stale or
rem --lite venv would otherwise train on pure-python while the operator believes the 4060
rem is working. So for cuda/cpu we require "import torch" inside this exact venv.
if not exist "%VPY%" goto :build_env
if "%MODE%"=="lite" goto :reuse_env
"%VPY%" -c "import torch" 1>nul 2>nul
if errorlevel 1 goto :build_env
goto :reuse_env

:build_env
call :log "STEP 1 building venv - shown live AND saved to setup.log; downloads torch up to ~2.4 GB; can take 5-20 min; do NOT close the window"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\setup.bat" -Arg "%*" -Log "%SETUPLOG%"
set "SRC=%errorlevel%"
call :log "STEP 1 setup.bat returned code=%SRC% - detail in setup.log"
if "%SRC%"=="0" goto :env_ready
call :log "STEP 1 FAILED - setup"
call :packlogs
echo [auto] setup failed - usually not enough disk space or no internet.
echo        Retry with a smaller mode:  AUTO.bat --cpu   or   AUTO.bat --lite
echo [auto] Send me  setup.log  and  auto.log   - setup.log has the real pip/python error.
exit /b 1

:reuse_env
call :log "STEP 1 reusing existing venv - backend check passed - python = %VPY%"
goto :env_ready

:env_ready
call :log "STEP 1 done - venv python = %VPY%"
rem Loud gate: if we asked for the GPU build but CUDA is not actually usable, STOP here
rem instead of silently training on pure-python for 5+ minutes and faking a good run.
if not "%MODE%"=="cuda" goto :numpy_step
"%VPY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 1>nul 2>nul
if not errorlevel 1 goto :cuda_ok
call :log "STEP 1 GPU GATE FAILED - mode=cuda but torch.cuda.is_available is false"
call :packlogs
echo [auto] The 4060 is NOT usable: torch is installed but CUDA is off.
echo        Usually the NVIDIA driver is missing or older than CUDA 12.1.
echo        Run  nvidia-smi  in a command prompt and compare the driver version.
echo        To proceed on CPU now anyway:  AUTO.bat --cpu   or   AUTO.bat --lite
echo [auto] Send me  setup.log  info.txt  auto.log.
exit /b 1

:cuda_ok
call :log "STEP 1 GPU GATE OK - CUDA is visible, torch will train on the 4060"
:numpy_step
if exist "%VPY%" "%VPY%" -c "import numpy" 1>nul 2>nul
if errorlevel 1 "%VPY%" -m pip install --no-cache-dir --retries 5 --timeout 120 numpy 1>nul 2>nul

call :log "STEP 2 of 3 - arent info, then timing CPU vs GPU (bench)"
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
    call :packlogs
    echo [auto] Send me  bench.log  info.txt  and  auto.log.
    exit /b 1
)

rem ---- STEP 3a: grow the dataset BEFORE training, so bc2 is not stuck on the frozen bundled
rem ---- bc1. Start from a COPY of bc1 (old scenarios + warm-start stay intact) and let
rem ---- `gen --append` label every arena plus any live captures, adding only states that are
rem ---- not already present (dataset.append dedups by state key). Best effort: if gen adds
rem ---- nothing we still train on bc1, so this run can never be worse than before.
call :log "STEP 3a gen - grow the dataset (copy bc1 to bcall, then append newly labelled states)"
set "TRAINSET=bc1"
if not exist "%BC1DS%" (
    call :log "STEP 3a SKIP - bundled data\samples\bc1.jsonl missing, training on --dataset bc1"
    goto :train_step
)
copy /y "%BC1DS%" "%BCALL%" 1>nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "gen --name bcall --append --count 600 --seed 7" -Log "%GENLOG%"
set "GRC=%errorlevel%"
call :log "STEP 3a gen done exit=%GRC% - detail in gen.log (this is the CPU-bound labelling step)"
set "BC1SZ=0"
for %%A in ("%BC1DS%") do set "BC1SZ=%%~zA"
for %%A in ("%BCALL%") do if exist %%A if %%~zA GTR %BC1SZ% set "TRAINSET=bcall"
call :log "STEP 3a dataset pick - TRAINSET=%TRAINSET% (bc1=%BC1SZ% bytes; bcall used only if larger)"
:train_step
call :log "STEP 3 - training bc2 from %TRAINSET% (warm bc1; best and last epoch always saved). LONG step: watch train.log grow."
rem Fresh-run guard: drop any previous bc2 so old files can never be mistaken for this run.
if exist "%BC2%" rmdir /s /q "%BC2%"
mkdir "%BC2%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "train --dataset %TRAINSET% --warm bc1 --name bc2 --epochs 200" -Log "%TRAINLOG%"
set "TRC=%errorlevel%"
call :log "STEP 3 train done exit=%TRC% - full log in train.log"
if not "%TRC%"=="0" (
    call :log "STEP 3 FAILED - training"
    call :packlogs
    echo [auto] Send me  train.log  and  auto.log.
    exit /b 1
)

rem Phase 0 outcome metric: let the trained bc2 play WHOLE fights (survival / clear rate).
rem Best effort on purpose: a missing or failed eval must never discard the good models, so
rem it is logged and packed when present but is NOT part of the hard artifact gate below.
set "EVALRUN=%RUNDIR%\eval_bc2"
set "EVALLOG=%~dp0eval.log"
call :log "STEP 3 evaluate - long-horizon outcome of bc2 (best effort, will not gate the run)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "evaluate --model bc2 --name eval_bc2 --rounds 8" -Log "%EVALLOG%"
set "ERC=%errorlevel%"
call :log "STEP 3 evaluate done exit=%ERC% - detail in eval.log"

call :log "checking that every required artifact exists and is not empty"
set "FAIL="
for %%F in (
    "%BC2%\model.json"
    "%BC2%\model_best.json"
    "%BC2%\summary.json"
    "%BC2%\history.json"
    "%BC2MAN%"
    "%TRAINLOG%"
    "%BENCH%"
    "%INFO%"
) do (
    if not exist %%F (
        call :log "ARTIFACT MISSING %%~F"
        set "FAIL=1"
    ) else (
        for %%A in (%%F) do if %%~zA LSS 1 (
            call :log "ARTIFACT EMPTY %%~F"
            set "FAIL=1"
        )
    )
)
if defined FAIL (
    call :log "ARTIFACT CHECK FAILED - results NOT packed"
    call :packlogs
    echo [auto] Send me  train.log  auto.log  and  logs-back.zip so I can read why nothing was produced.
    exit /b 1
)

call :log "packing results-back.zip"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
copy /y "%BC2%\model.json"       "%OUT%\" 1>nul 2>nul
copy /y "%BC2%\model_best.json"  "%OUT%\" 1>nul 2>nul
copy /y "%BC2%\summary.json"     "%OUT%\" 1>nul 2>nul
copy /y "%BC2%\history.json"     "%OUT%\" 1>nul 2>nul
rem Provenance must travel back with the model, otherwise bc2's dataset stays unmeasurable
rem (the exact gap that left bcall + run_manifest behind on the 4060 last iteration).
copy /y "%BC2MAN%"               "%OUT%\" 1>nul 2>nul
if exist "%SAMPLES%\%TRAINSET%.jsonl" copy /y "%SAMPLES%\%TRAINSET%.jsonl" "%OUT%\" 1>nul 2>nul
if exist "%SAMPLES%\%TRAINSET%.jsonl.meta.json" copy /y "%SAMPLES%\%TRAINSET%.jsonl.meta.json" "%OUT%\" 1>nul 2>nul
copy /y "%TRAINLOG%"             "%OUT%\" 1>nul 2>nul
copy /y "%BENCH%"                "%OUT%\" 1>nul 2>nul
copy /y "%INFO%"                 "%OUT%\" 1>nul 2>nul
if exist "%BENCHLOG%" copy /y "%BENCHLOG%" "%OUT%\" 1>nul 2>nul
if exist "%SETUPLOG%" copy /y "%SETUPLOG%" "%OUT%\" 1>nul 2>nul
if exist "%GENLOG%" copy /y "%GENLOG%" "%OUT%\" 1>nul 2>nul
if exist "%AUTOLOG%" copy /y "%AUTOLOG%"   "%OUT%\" 1>nul 2>nul
if exist "%EVALRUN%\eval.json" copy /y "%EVALRUN%\eval.json" "%OUT%\" 1>nul 2>nul
if exist "%EVALLOG%" copy /y "%EVALLOG%" "%OUT%\" 1>nul 2>nul
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Force -DestinationPath '%ZIP%' -Path '%OUT%\*'"
if errorlevel 1 (
    call :log "FAILED to build the zip"
    exit /b 1
)
rem Prove the zip really carries the required artifacts before claiming success.
powershell -NoProfile -ExecutionPolicy Bypass -File "%ARENT%\pack\verify_zip.ps1" "%ZIP%"
if errorlevel 1 (
    call :log "archive INCOMPLETE - see the check above"
    exit /b 1
)

rem ---- STEP 4: the decisive long-horizon A/B, delegated to AB.bat so that recipe lives
rem ---- in exactly one place. ARENT_CALLED tells AB.bat to skip its own pauses so the whole
rem ---- AUTO.bat run stays keypress-free. A/B is NON-FATAL: results-back.zip is already
rem ---- packed and verified above, so whatever AB.bat returns we still reach DONE below.
call :log "STEP 4 - long-horizon A/B via AB.bat - LONG step: labels twice, trains twice, evaluates twice"
set "ARENT_CALLED=1"
call "%~dp0AB.bat"
set "ABRC=%errorlevel%"
set "ARENT_CALLED="
call :log "STEP 4 A/B finished exit=%ABRC% - see ab.log and ab-back.zip next to AUTO.bat"

call :log "DONE - exit 0"
echo.
echo [auto] DONE. Send me these files (all next to AUTO.bat):
echo        %ZIP%
echo        %~dp0ab-back.zip
echo        %AUTOLOG%
echo        results-back.zip : model.json, model_best.json, summary.json, history.json,
echo        train.log, bench.log, bench.json, info.txt, setup.log, auto.log, eval.json + eval.log,
echo        run_manifest.json + the training dataset (%TRAINSET%.jsonl) for provenance
echo        ab-back.zip      : abA_eval.json vs abB_eval.json + summaries - the A/B outcome
echo [auto] DONE line is also the last line of auto.log - nothing waits for a keypress.
exit /b 0

:log
rem Append one timestamped marker to auto.log and flush it immediately, then mirror to screen.
>>"%AUTOLOG%" echo %DATE% %TIME% - %~1
echo [%TIME%] [auto] %~1
exit /b 0

:packlogs
rem Bundle whatever logs exist so far into logs-back.zip (used on every failure path).
set "L=%~dp0logs"
if exist "%L%" rmdir /s /q "%L%"
mkdir "%L%" 1>nul 2>nul
if exist "%SETUPLOG%" copy /y "%SETUPLOG%" "%L%\" 1>nul 2>nul
if exist "%INFO%"     copy /y "%INFO%"     "%L%\" 1>nul 2>nul
if exist "%BENCHLOG%" copy /y "%BENCHLOG%" "%L%\" 1>nul 2>nul
if exist "%TRAINLOG%" copy /y "%TRAINLOG%" "%L%\" 1>nul 2>nul
if exist "%BENCH%"    copy /y "%BENCH%"    "%L%\" 1>nul 2>nul
if exist "%AUTOLOG%"  copy /y "%AUTOLOG%"  "%L%\" 1>nul 2>nul
if exist "%~dp0logs-back.zip" del /q "%~dp0logs-back.zip" 1>nul 2>nul
powershell -NoProfile -Command "Compress-Archive -Force -DestinationPath '%~dp0logs-back.zip' -Path '%L%\*'" 1>nul 2>nul
if exist "%~dp0logs-back.zip" echo [auto] wrote %~dp0logs-back.zip
exit /b 0
