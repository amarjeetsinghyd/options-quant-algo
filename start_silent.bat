@echo off
title Quant Terminal Silent Launcher
cd /d "%~dp0"

echo Shutting down any previous ghost python processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1

echo Launching Quant Backend silently in the background...
powershell -WindowStyle Hidden -Command "Start-Process '.\venv\Scripts\pythonw.exe' -ArgumentList 'start_all.py' -WindowStyle Hidden"

echo Backend is now running silently! You may close this window.
timeout /t 3 >nul
