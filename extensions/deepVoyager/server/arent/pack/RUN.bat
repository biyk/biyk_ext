@echo off
rem RUN.bat - the ONE launcher. Double-click it from the unpacked folder.
rem
rem   Layout (by design, so heavy stuff survives replacing the code):
rem     RUN.bat    <- this file (overwrite it every handoff)
rem     server\    <- CODE ONLY. Delete and replace freely; nothing valuable lives here.
rem     state\     <- models (runs\) + datasets (data\). OUTSIDE server, kept between handoffs.
rem     venv\      <- torch env. OUTSIDE server, built once, NEVER re-downloaded on a code swap.
rem
rem   What it does (by DEFAULT): makes sure venv\ has the backend, builds the v2 stack if
rem   missing - BC v2 (gen+train into state\runs\bc_v2, skipped when it exists) and a
rem   TEAM-REWARD PPO warm from bc_v2 into state\runs\ppo_v2 (idempotent - skipped if
rem   ppo_v2 exists, bc_v2 never overwritten) - then evaluates bc_v2 AND the v2 ppo on the
rem   independent ho_* + ho2_* set, and packs ONE result.zip next to this file carrying every
rem   log AND a copy of your full state\. Send me result.zip - that is the whole loop. The
rem   ONLY new file after a run is result.zip. Old-schema checkpoints are skipped, not evaluated.
rem
rem   So just DOUBLE-CLICK RUN.bat - no typing (that already trains PPO + fair-compares).
rem   First run only, to change the 4060 build:  RUN.bat --cpu  |  RUN.bat --lite  |  RUN.bat --offline
rem   Only a quick re-compare, no training:       RUN.bat --eval-only
rem   Force task schema (else uses schema.txt):   RUN.bat --v3    |  RUN.bat --v2
rem   More/fewer PPO iterations:                  RUN.bat 300     (RUN.bat --train still works too)
setlocal enableextensions
cd /d "%~dp0"

set "ARENT=%~dp0server\arent"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

set "MODE=cuda"
set "HX="
set "ITERS="
set "EVALONLY="
set "SCHEMAARG="
set "SV="
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--cpu" set "MODE=cpu"& shift & goto parse
if /i "%~1"=="--lite" set "MODE=lite"& shift & goto parse
if /i "%~1"=="--offline" set "MODE=offline"& shift & goto parse
if /i "%~1"=="--train" shift & goto parse
if /i "%~1"=="--v3" set "SCHEMAARG=-Schema 3"& shift & goto parse
if /i "%~1"=="--schema3" set "SCHEMAARG=-Schema 3"& shift & goto parse
if /i "%~1"=="--v2" set "SCHEMAARG="& set "V2FORCE=1"& shift & goto parse
if /i "%~1"=="--eval-only" set "EVALONLY=1"& set "HX=-EvalOnly"& shift & goto parse
if /i "%~1"=="--no-train" set "EVALONLY=1"& set "HX=-EvalOnly"& shift & goto parse
set "A=%~1"
if not "x%A:~0,2%"=="x--" set "ITERS=%A%"
shift
goto parse
:parsed
rem default schema for a bare double-click: a shipped schema.txt holding 3 makes this a v3 box;
rem an explicit --v3 / --v2 overrides it, and --v2 wins even when schema.txt says 3.
if defined V2FORCE set "SCHEMAARG="
if not defined SCHEMAARG if exist "%~dp0schema.txt" set /p SV=<"%~dp0schema.txt"
if not defined SCHEMAARG if "%SV%"=="3" set "SCHEMAARG=-Schema 3"
if defined ITERS set "HX=%HX% -Iters %ITERS%"

echo [run] folder: %~dp0
echo [run] live log + a backup of your models go INSIDE result.zip - you send back one file.
if defined EVALONLY (echo [run] mode: EVALUATE-ONLY - only compare the checkpoints on the independent set) else (echo [run] mode: FULL - train BC if absent, then team-reward PPO, then compare. first run LONG; re-run skips finished steps)
if "%SCHEMAARG%"=="-Schema 3" (echo [run] schema: 3 - move-plan action space, team scenarios, fair comparison on ho3_* only) else (echo [run] schema: 2 - v2 cell-action stack, comparison on ho_*/ho2_*)
echo.

if not exist "%ARENT%\main.py" goto :no_server
powershell -NoProfile -ExecutionPolicy Bypass -File "%ARENT%\pack\no_quickedit.ps1" 1>nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%ARENT%\pack\handoff.ps1" -Mode %MODE% %SCHEMAARG% %HX%
set "RC=%errorlevel%"

echo.
if not exist "%~dp0result.zip" goto :no_zip
echo [run] DONE. Send me ONLY this ONE file:
echo         %~dp0result.zip
echo       it holds every report AND a copy of your models + datasets, so nothing is lost.
if not "%RC%"=="0" echo [run] note: exited code %RC% - result.zip still has the details (error.txt inside).
pause
exit /b 0

:no_zip
>>"%~dp0handoff_error.txt" echo RUN.bat: no result.zip produced, exit=%RC% %DATE% %TIME%
echo [run] FAILED (exit=%RC%) and result.zip was not produced.
echo         If the window scrolled past an error, screenshot it and send it to me.
pause
exit /b 1

:no_server
echo [run] server\arent\main.py not found. Unpack the WHOLE archive (RUN.bat next to server\) first.
pause
exit /b 1
