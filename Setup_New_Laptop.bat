@echo off
echo ========================================================
echo QUANT ALGO - NEW LAPTOP SETUP SCRIPT
echo ========================================================
echo.
echo This script will automatically configure this folder to run on your new laptop.
echo It will rebuild the Node.js modules and Python Virtual Environment.
echo.
pause

echo.
echo [1/3] Deleting old system files...
if exist "node_modules" rmdir /s /q "node_modules"
if exist "venv" rmdir /s /q "venv"

echo.
echo [2/3] Installing Node.js packages (Electron)...
call npm install

echo.
echo [3/3] Creating new Python Virtual Environment and installing libraries...
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ========================================================
echo SETUP COMPLETE! 
echo ========================================================
echo You can now double-click "Run test.vbs" to start the algo.
echo Note: If you want a desktop shortcut, right-click "Run test.vbs" -^> Send To -^> Desktop.
echo.
pause
