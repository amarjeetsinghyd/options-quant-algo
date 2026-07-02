@echo off
title Quant Terminal Server (Headless)
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo WARNING: virtual environment not found at venv\Scripts\activate.bat
)

REM Start the master process manager which handles all microservices
REM Running in headless mode (no browser auto-open)
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" start_all.py
) else (
    echo WARNING: virtual environment python.exe not found, using system python.
    python start_all.py
)
