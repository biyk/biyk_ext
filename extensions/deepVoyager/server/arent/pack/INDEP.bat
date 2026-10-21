@echo off
rem INDEP.bat - honest bc2 vs PPO comparison on the RESERVED independent set (ho_*).
rem
rem   Trains NOTHING and creates NO new weights. It only EVALUATES the already existing
rem   checkpoints (runs\bc2, runs\ppo_pilot) on the reserved ho_* scenarios via
rem   `evaluate --independent`, then returns the FULL reports in indep-back.zip.
rem   If eval_bc2_ho / eval_ppo_ho already exist, are valid and cover the SAME set
rem   (identical testset_sha256), they are REUSED as-is; otherwise exactly one
rem   re-evaluation of the existing checkpoints is run (an eval, never training).
rem
rem   Usage (after AUTO.bat, next to the "server" folder inside the unpacked archive):
rem     INDEP.bat                     bc2 vs ppo_pilot, rounds 8
rem     INDEP.bat --ppo ppo1          pick the PPO run name
rem     INDEP.bat --force             re-evaluate even if a valid eval already exists
rem
rem   No model*, summary, run_manifest or dataset is touched. Only the eval result
rem   folders eval_bc2_ho / eval_ppo_ho (results, not weights) may be rewritten.
setlocal enableextensions
cd /d "%~dp0"

set "ILOG=%~dp0indep.log"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

set "PPO=ppo_pilot"
set "KIND=torch"
set "ROUNDS=8"
set "FORCEFLAG="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--force" set "FORCEFLAG=-Force"
if /i "%~1"=="--ppo" set "PPO=%~2" & shift
set "A=%~1"
if not "x%A:~0,2%"=="x--" set "ROUNDS=%A%"
shift
goto parse
:parsed

> "%ILOG%" echo INDEP.bat run start %DATE% %TIME%  cwd=%CD%  ppo=%PPO% kind=%KIND% rounds=%ROUNDS% %FORCEFLAG%
echo [indep] live log : %ILOG%
echo.

set "ARENT="
if exist "server\arent\main.py" set "ARENT=server\arent"
if not defined ARENT if exist "arent\main.py" set "ARENT=arent"
if not defined ARENT if exist "main.py" set "ARENT=."
if not defined ARENT (
    >>"%ILOG%" echo FATAL - arent folder not found next to INDEP.bat
    echo [indep] Unpack the ENTIRE archive, then run the INDEP.bat inside it.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%ARENT%\pack\no_quickedit.ps1" 1>nul 2>nul

call :log "STEP 1 - collect/evaluate independent (ho_*) comparison of existing checkpoints"
set "RUNTXT=%~dp0indep_run.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%ARENT%\pack\indep_eval.ps1" -Arent "%~dp0%ARENT%" -PpoName "%PPO%" -Rounds %ROUNDS% -Kind %KIND% %FORCEFLAG% > "%RUNTXT%" 2>&1
set "RC=%errorlevel%"
type "%RUNTXT%"
>>"%ILOG%" type "%RUNTXT%"
call :log "STEP 1 done exit=%RC% - indep-back.zip next to INDEP.bat"
echo.
echo [indep] DONE. Send me these (next to INDEP.bat):
echo         %~dp0indep-back.zip   (eval_bc2_ho.json + eval_ppo_ho.json full + indep_manifest.json + indep_report.txt + manifests)
echo         %~dp0indep.log
echo [indep] indep_report.txt already holds the bc2 vs PPO table on the identical independent set.
exit /b %RC%

:log
>>"%ILOG%" echo %DATE% %TIME% - %~1
echo [%TIME%] [indep] %~1
exit /b 0
