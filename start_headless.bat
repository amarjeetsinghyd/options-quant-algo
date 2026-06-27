@echo off
title Quant Terminal Server (Headless)
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Start the master process manager which handles all microservices
REM Running in headless mode (no browser auto-open)
python start_all.py
