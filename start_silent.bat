@echo off
title Quant Terminal Silent Launcher
cd /d "%~dp0"

echo Looking for prior Quant Engine process...
if exist "data\quant_engine.pid" (
    for /f "usebackq tokens=*" %%P in ("data\quant_engine.pid") do (
        echo Attempting graceful stop of Quant Engine PID %%P
        taskkill /PID %%P /T >nul 2>&1
    )
)

echo Launching Quant Backend silently in the background...
if exist "venv\Scripts\pythonw.exe" (
    powershell -WindowStyle Hidden -Command "Start-Process '.\venv\Scripts\pythonw.exe' -ArgumentList 'start_all.py' -WorkingDirectory '%cd%' -WindowStyle Hidden"
) else (
    echo Virtual environment pythonw.exe not found. Falling back to system python.
    powershell -WindowStyle Hidden -Command "Start-Process 'python.exe' -ArgumentList 'start_all.py' -WorkingDirectory '%cd%' -WindowStyle Hidden"
)

echo Backend is now running silently! You may close this window.
timeout /t 3 >nul
