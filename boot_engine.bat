@echo off
title Autonomous Quant Engine
echo Booting Autonomous Quant Engine...
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
python start_all.py
