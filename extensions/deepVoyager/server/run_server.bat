@echo off
rem Start deepVoyager Flask server (port 9999) in THIS visible console window.
cd /d "%~dp0"
echo [run_server] folder: %~dp0
echo [run_server] starting server.py (Ctrl+C or close window to stop)
".venv\Scripts\python.exe" server.py
echo.
echo [run_server] server stopped.
pause
