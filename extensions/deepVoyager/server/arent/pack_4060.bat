@echo off
rem arent\pack_4060.bat - pack the whole training project into one zip for the 4060 machine.
rem
rem   pack_4060.bat          code + arenas + live snapshots + datasets + checkpoints
rem   pack_4060.bat --lean   code and config only (fresh machine that starts from zero)
rem
rem The zip lands in Data\modules\biyk_ext\temp (gitignored, safe to delete). It never
rem contains .venv, build, dist, logs, __pycache__ or .env - the target machine builds
rem its own environment with START_HERE.bat / setup.bat.
setlocal
cd /d "%~dp0"

set "EXTRA="
if /i "%~1"=="--lean" set "EXTRA=-Lean"
if not "%~2"=="" set "EXTRA=%EXTRA% -Name %~2"

powershell -NoProfile -ExecutionPolicy Bypass -File "pack\make_zip.ps1" %EXTRA%
if errorlevel 1 echo [pack] FAILED - read the lines above.
endlocal
