@echo off
title Autonomous Quant Engine
echo Booting Autonomous Quant Engine...
cd /d "C:\Users\Amarjeet Singh\quant_algo_test"
set POLARS_IGNORE_TIMEZONE_PARSE_ERROR=1
"C:\Users\Amarjeet Singh\quant_algo_test\venv\Scripts\python.exe" start_all.py > boot_error.log 2>&1
