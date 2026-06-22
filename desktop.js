const { app, BrowserWindow, Tray, Menu } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let mainWindow;
let tray;
let pythonProcess;

// Prevent multiple instances
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
    app.quit();
} else {
    app.on('second-instance', () => {
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
        }
    });

    app.on('ready', () => {
        // Create log stream
        const logPath = path.join(__dirname, 'logs', 'electron_python.log');
        const logStream = fs.createWriteStream(logPath, { flags: 'a' });
        
        // 1. Spawn Python Engine using the virtual environment
        logStream.write(`\n\n[${new Date().toISOString()}] Starting Python Background Engine...\n`);
        const pythonExecutable = path.join(__dirname, 'venv', 'Scripts', 'python.exe');
        pythonProcess = spawn(pythonExecutable, ['main.py'], {
            cwd: __dirname,
            windowsHide: true,
        });

        pythonProcess.stdout.on('data', (data) => {
            logStream.write(data);
        });

        pythonProcess.stderr.on('data', (data) => {
            logStream.write(`[ERROR] ${data}`);
        });

        pythonProcess.on('close', (code) => {
            logStream.write(`[Python] process exited with code ${code}\n`);
        });

        // 2. Create the Desktop Window
        mainWindow = new BrowserWindow({
            width: 1200,
            height: 800,
            title: 'Quant Algorithmic Terminal',
            autoHideMenuBar: true,
            icon: path.join(__dirname, 'icon.ico') // Optional icon
        });

        // Give Python 2 seconds to boot the Flask server before loading
        setTimeout(() => {
            mainWindow.loadURL('http://127.0.0.1:5000');
        }, 2000);

        // 3. System Tray Logic
        // Intercept close (X) button to hide instead of quit
        mainWindow.on('close', (event) => {
            if (!app.isQuitting) {
                event.preventDefault();
                mainWindow.hide();
                console.log("App minimized to System Tray.");
            }
            return false;
        });

        // Create Tray Icon (Using a default built-in icon or custom if exists)
        // Note: Electron requires an image for the tray. We will use a simple circle if icon is missing.
        try {
            tray = new Tray(path.join(__dirname, 'icon.png')); // Fallback if exists
        } catch (e) {
            // NativeImage fallback if no icon exists
            const { nativeImage } = require('electron');
            const icon = nativeImage.createEmpty();
            tray = new Tray(icon);
            tray.setTitle("Quant");
        }
        
        tray.setToolTip('Quant Algorithmic Terminal - Running in Background');

        const contextMenu = Menu.buildFromTemplate([
            { label: 'Show Dashboard', click: () => mainWindow.show() },
            { type: 'separator' },
            { 
                label: 'Quit Algo Completely', 
                click: () => {
                    app.isQuitting = true;
                    if (pythonProcess) {
                        try {
                            // Kill the python process tree on Windows
                            spawn("taskkill", ["/pid", pythonProcess.pid, '/f', '/t']);
                        } catch (e) {}
                    }
                    app.quit();
                } 
            }
        ]);
        
        tray.setContextMenu(contextMenu);
        
        tray.on('click', () => {
            mainWindow.show();
        });
    });

    // Cleanup on exit
    app.on('will-quit', () => {
        if (pythonProcess) {
            try {
                spawn("taskkill", ["/pid", pythonProcess.pid, '/f', '/t']);
            } catch (e) {}
        }
    });
}
