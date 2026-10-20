@echo off
rem START_HERE.bat - one click bootstrap on the machine you train on (RTX 4060 or any other).
rem Double-click it from the unpacked folder. It does three things and stops on problems:
rem   1. checks that python 3.10+ exists
rem   2. runs server\arent\setup.bat (pass flags through: START_HERE.bat --cpu / --lite / --offline)
rem   3. runs server\arent\arent.bat info, which prints what arent can see
rem Read START_HERE.txt for the commands that come next.
setlocal
cd /d "%~dp0"

echo.
echo [start] folder: %cd%
echo [start] STEP 1/3 - checking python
set "BASE=python"
where py >nul 2>nul
if not errorlevel 1 set "BASE=py -3"
%BASE% -V 2>nul
if errorlevel 1 (
    echo [start] NO PYTHON FOUND. Install Python 3.10 or newer from python.org,
    echo         tick "Add python.exe to PATH", then run this file again.
    pause
    exit /b 1
)

echo.
echo [start] STEP 2/3 - environment (torch download needs internet and free disk)
echo         modes: (default) CUDA ~8 GB free ^| --cpu ~3 GB ^| --lite ~1 GB ^| --offline ~3 GB
if not exist "server\arent\setup.bat" (
    echo [start] server\arent\setup.bat is missing - the archive was unpacked wrongly.
    pause
    exit /b 1
)
call server\arent\setup.bat %*
if errorlevel 1 (
    echo [start] setup failed. You can still train without torch:
    echo         server\arent\arent.bat train --lite is not a flag - instead run
    echo         setup.bat --lite, or just continue with the commands in START_HERE.txt,
    echo         because gen / train / play / bench work on bare python too.
    pause
    exit /b 1
)

echo.
echo [start] STEP 3/3 - what arent sees
pushd server\arent
arent.bat info
popd

echo.
echo [start] done. Want ZERO typing? Double-click RUN_ALL.bat in this same folder -
echo         it builds the env, benchmarks GPU vs CPU and trains the model by itself.
echo [start] Or drive by hand from server\arent:
echo          arent.bat bench --epochs 5            - time pure vs torch vs cuda
echo          arent.bat train --dataset bc1 --warm bc1 --name bc2 --epochs 200
echo          arent.bat gen --count 1000 --per-src 12 --name big1 --append
echo          arent.bat play --model bc2 --payload data\payloads\arena1_live.json
echo.
echo Read START_HERE.txt for the full notes.
pause
endlocal
