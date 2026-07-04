@echo off
title Autonomous Quant Engine
echo Booting Autonomous Quant Engine in Background...
cd /d "%~dp0"
start "" venv\Scripts\pythonw.exe bootstrap.py
echo Quant Engine has been started in the background.
echo You can now close this window safely.
exit
