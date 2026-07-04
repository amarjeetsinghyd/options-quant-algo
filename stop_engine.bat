@echo off
title Stop Quant Engine
cd /d "%~dp0"
echo Requesting graceful shutdown of the Quant Engine...
venv\Scripts\python.exe shutdown.py
pause
