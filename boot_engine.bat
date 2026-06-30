@echo off
title Autonomous Quant Engine
echo Booting Autonomous Quant Engine in Background via PM2...
cd /d "C:\Users\Amarjeet Singh\quant_algo_test"
pm2 start ecosystem.config.js
pm2 save
echo Quant Engine has been started in the background.
echo You can now close this window safely.
timeout /t 5 >nul
