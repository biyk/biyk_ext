@echo off
rem Start deepVoyager Flask server (port 9999) in THIS visible console window.
cd /d "%~dp0"
echo [run_server] folder: %~dp0
echo [run_server] starting server.py (Ctrl+C or close window to stop)
".venv\Scripts\python.exe" server.py
echo.
rem Normal stop (Ctrl+C / killed process, rc<1) closes the window by itself; only a crash stays open.
if errorlevel 1 (
    echo [run_server] server exited with an error, read the log above.
    pause
) else (
    echo [run_server] server stopped, closing window.
    timeout /t 2 /nobreak >nul
)
