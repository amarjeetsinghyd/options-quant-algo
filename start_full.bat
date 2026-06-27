@echo off
title Quant Terminal Server
echo ========================================================
echo Quant Terminal - Microservices Backend
echo ========================================================
echo.
echo Leave this window open while trading.
echo To stop the algorithm, close this window or press Ctrl+C.
echo.
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Background delay to open the UI in browser after services spin up
start /B cmd /c "timeout /t 5 >nul & start http://127.0.0.1:5000/"

REM Start the master process manager which handles all microservices
python start_all.py
