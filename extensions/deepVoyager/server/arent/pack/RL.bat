@echo off
rem RL.bat - Phase 1: PPO over the fight outcome (long horizon), warm-started from bc2.
rem
rem   Run AUTO.bat FIRST (it produces runs\bc2\model_best.json). Then:
rem     RL.bat              PPO on the 4060 (cuda), default 120 iterations
rem     RL.bat 300          PPO for 300 iterations
rem     RL.bat --cpu        force the CPU backend if the 4060 is not usable
rem
rem   What it does, one click, never waits for a keypress:
rem     1. same venv + CUDA gate as AUTO.bat (reuses the torch env AUTO built)
rem     2. arent rl --warm bc2 --name ppo1   (PPO on the same frozen scenarios)
rem     3. arent evaluate --model ppo1        (the honest closed-loop outcome)
rem     4. packs ppo-back.zip and verifies it with verify_zip.ps1
rem   Send back ppo-back.zip + rl.log. bc2 stays untouched, so BC remains the fallback.
rem
rem   The PPO checkpoint keeps the SAME network dims and the SAME checkpoint FORMAT as BC,
rem   so it loads anywhere BC loads. If it does not beat the BC baseline, that is recorded
rem   honestly in eval.json / run_manifest.json - it is a measurement, not a claim.
setlocal enableextensions
cd /d "%~dp0"

set "RLLOG=%~dp0rl.log"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

set "MODE=cuda"
set "ITERS=120"
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--cpu" set "MODE=cpu"
if /i "%~1"=="--lite" set "MODE=lite"
if /i "%~1"=="--offline" set "MODE=offline"
set "A=%~1"
if not "x%A:~0,2%"=="x--" set "ITERS=%A%"
shift
goto parse
:parsed

> "%RLLOG%" echo RL.bat run start %DATE% %TIME%  cwd=%CD%  iters=%ITERS% mode=%MODE%
echo [rl] live step log :  %RLLOG%
echo.

set "ARENT="
if exist "server\arent\main.py" set "ARENT=server\arent"
if not defined ARENT if exist "arent\main.py" set "ARENT=arent"
if not defined ARENT if exist "main.py" set "ARENT=."
if not defined ARENT (
    call :log "FATAL - arent folder not found next to RL.bat"
    echo [rl] Unpack the ENTIRE archive, then run the RL.bat inside it.
    exit /b 1
)

set "HELPER=%~dp0%ARENT%\pack\run_logged.ps1"
set "VPY=%ARENT%\.venv\Scripts\python.exe"
set "RUNDIR=%ARENT%\runs"
set "BC2=%RUNDIR%\bc2"
set "PPO=%RUNDIR%\ppo1"
set "PPOEVAL=%RUNDIR%\eval_ppo1"
set "POPMAN=%PPO%\run_manifest.json"
set "TRAINLOG=%PPO%\rl_run.log"
set "EVALLOG=%~dp0eval_ppo.log"
set "SETUPLOG=%~dp0setup.log"
set "OUT=%~dp0ppo-back"
set "ZIP=%~dp0ppo-back.zip"
set "INFO=%~dp0info.txt"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%ARENT%\pack\no_quickedit.ps1" 1>nul 2>nul

call :log "STEP 1 - environment (same venv + CUDA gate as AUTO.bat)"
if not exist "%VPY%" goto :build_env
if "%MODE%"=="lite" goto :reuse_env
"%VPY%" -c "import torch" 1>nul 2>nul
if errorlevel 1 goto :build_env
goto :reuse_env

:build_env
call :log "STEP 1 building venv - shown live AND saved to setup.log (run AUTO.bat first to reuse its env)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\setup.bat" -Arg "%MODE%" -Log "%SETUPLOG%"
set "SRC=%errorlevel%"
if not "%SRC%"=="0" (
    call :log "STEP 1 FAILED - setup returned %SRC% (see setup.log)"
    exit /b 1
)
goto :env_ready

:reuse_env
call :log "STEP 1 reusing existing venv - python = %VPY%"
:env_ready
if "%MODE%"=="cuda" (
    "%VPY%" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 1>nul 2>nul
    if errorlevel 1 (
        call :log "STEP 1 GPU GATE FAILED - mode=cuda but no CUDA; rerun  RL.bat --cpu"
        exit /b 1
    )
    call :log "STEP 1 GPU GATE OK"
)

rem ---- PPO needs its BC parent. Without runs\bc2\model_best.json there is nothing to
rem ---- warm-start from, so we stop with a clear pointer instead of failing deep inside rl.
if not exist "%BC2%\model_best.json" (
    call :log "STEP 2 SKIP - no warm parent runs\bc2\model_best.json. Run AUTO.bat first."
    echo [rl] There is no bc2 to warm-start PPO from. Run AUTO.bat first, then RL.bat.
    exit /b 1
)

set "DEVKIND=cuda"
if not "%MODE%"=="cuda" set "DEVKIND=cpu"

call :log "STEP 2 - arent info (record the backend before training)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "info" -Log "%INFO%" 1>nul 2>nul

call :log "STEP 3 - PPO warm from bc2, %ITERS% iterations, LONG step: watch rl_run.log grow"
if exist "%PPO%" rmdir /s /q "%PPO%"
mkdir "%PPO%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "rl --warm bc2 --name ppo1 --iters %ITERS% --rounds 8 --replays 3 --kind torch --device %DEVKIND%" -Log "%TRAINLOG%"
set "RLRC=%errorlevel%"
call :log "STEP 3 rl done exit=%RLRC% - full log in rl_run.log"
if not "%RLRC%"=="0" (
    call :log "STEP 3 FAILED - PPO training"
    echo [rl] Send me  rl_run.log  and  rl.log
    exit /b 1
)

call :log "STEP 4 - honest closed-loop eval of ppo1 (outcome, not one move)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Script "%~dp0%ARENT%\arent.bat" -Arg "evaluate --model ppo1 --name eval_ppo1 --rounds 8 --kind torch" -Log "%EVALLOG%"
set "ERC=%errorlevel%"
call :log "STEP 4 evaluate done exit=%ERC% - detail in eval_ppo.log (best effort, does not gate packing)"

call :log "checking required PPO artifacts"
set "FAIL="
for %%F in (
    "%PPO%\model.json"
    "%PPO%\model_best.json"
    "%PPO%\summary.json"
    "%PPO%\history.json"
    "%POPMAN%"
    "%TRAINLOG%"
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
    echo [rl] Send me  rl_run.log  and  rl.log  so I can read why nothing was produced.
    exit /b 1
)

call :log "packing ppo-back.zip"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
copy /y "%PPO%\model.json"       "%OUT%\" 1>nul 2>nul
copy /y "%PPO%\model_best.json"  "%OUT%\" 1>nul 2>nul
copy /y "%PPO%\summary.json"     "%OUT%\" 1>nul 2>nul
copy /y "%PPO%\history.json"     "%OUT%\" 1>nul 2>nul
copy /y "%POPMAN%"               "%OUT%\" 1>nul 2>nul
copy /y "%TRAINLOG%"             "%OUT%\" 1>nul 2>nul
if exist "%INFO%"                copy /y "%INFO%" "%OUT%\" 1>nul 2>nul
if exist "%EVALLOG%"             copy /y "%EVALLOG%" "%OUT%\" 1>nul 2>nul
if exist "%PPOEVAL%\eval.json"   copy /y "%PPOEVAL%\eval.json" "%OUT%\" 1>nul 2>nul
if exist "%BC2%\eval.json"       copy /y "%BC2%\eval.json" "%OUT%\bc2_eval.json" 1>nul 2>nul
if exist "%RLLOG%"               copy /y "%RLLOG%" "%OUT%\" 1>nul 2>nul
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Force -DestinationPath '%ZIP%' -Path '%OUT%\*'"
if errorlevel 1 (
    call :log "FAILED to build the zip"
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ARENT%\pack\verify_zip.ps1" "%ZIP%" -Need model.json model_best.json summary.json history.json run_manifest.json rl_run.log
if errorlevel 1 (
    call :log "archive INCOMPLETE - see the check above"
    exit /b 1
)

call :log "DONE - exit 0"
echo.
echo [rl] DONE. Send me these files (all next to RL.bat):
echo        %ZIP%
echo        %RLLOG%
echo        ppo-back.zip : model.json, model_best.json, summary.json, history.json,
echo        run_manifest.json, rl_run.log, eval.json (ppo1) + bc2_eval.json baseline + info.txt
echo [rl] The PPO-vs-BC comparison lives in the two eval.json files - improvement is a
echo        measurement, only claimed if ppo1 beats the frozen bc2 baseline.
exit /b 0

:log
>>"%RLLOG%" echo %DATE% %TIME% - %~1
echo [%TIME%] [rl] %~1
exit /b 0
