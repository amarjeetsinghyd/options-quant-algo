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
        
        // 1. Python Engine Management
        // We spawn the engine natively and invisibly using child_process.spawn
        let pythonProcess = null;
        let isIntentionalQuit = false;

        function startPythonBackend() {
            logStream.write(`\n\n[${new Date().toISOString()}] Booting Python backend natively...\n`);
            
            let pythonExecutable = path.join(__dirname, 'venv', 'Scripts', 'pythonw.exe');
            if (!fs.existsSync(pythonExecutable)) {
                pythonExecutable = 'python';
            }

            pythonProcess = spawn(pythonExecutable, ['main.py'], {
                cwd: __dirname,
                windowsHide: true,
                detached: true
            });

            pythonProcess.unref();

            pythonProcess.stdout.on('data', (data) => {
                logStream.write(`[PYTHON] ${data}`);
            });

            pythonProcess.stderr.on('data', (data) => {
                logStream.write(`[PYTHON ERROR] ${data}`);
            });

            pythonProcess.on('close', (code, signal) => {
                logStream.write(`[PYTHON] Process exited with code ${code} and signal ${signal}\n`);
                if (!isIntentionalQuit) {
                    logStream.write(`[PYTHON] Unexpected crash detected. Auto-restarting in 2 seconds...\n`);
                    setTimeout(startPythonBackend, 2000);
                }
            });
        }

        // Start it for the first time
        startPythonBackend();

        // 2. Create the Desktop Window
        mainWindow = new BrowserWindow({
            width: 1200,
            height: 800,
            title: 'Quant Algorithmic Terminal',
            autoHideMenuBar: true,
            icon: path.join(__dirname, 'icon.ico') // Optional icon
        });

        // Give Python time to boot the Flask server before loading
        const maxRetries = 30;
        let retries = 0;
        const checkServer = () => {
            const http = require('http');
            const req = http.get('http://127.0.0.1:5000', (res) => {
                if (res.statusCode === 200) {
                    mainWindow.loadURL('http://127.0.0.1:5000');
                } else {
                    retry();
                }
            }).on('error', (err) => {
                retry();
            });
            req.end();
        };

        const retry = () => {
            retries++;
            if (retries < maxRetries) {
                setTimeout(checkServer, 1000);
            } else {
                console.log("Failed to connect to Python server after 30 seconds.");
                // Load anyway so dev tools can be opened to debug, or show an error
                mainWindow.loadURL('http://127.0.0.1:5000');
            }
        };

        // Start checking after 1 second
        setTimeout(checkServer, 1000);

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
            { 
                label: 'Quit UI', 
                click: () => {
                    app.isQuitting = true;
                    app.quit();
                } 
            },
            {
                label: 'Quit Algo Completely (Stop Trading)',
                click: () => {
                    app.isQuitting = true;
                    isIntentionalQuit = true;
                    if (pythonProcess) {
                        try {
                            process.kill(-pythonProcess.pid); // Kill process tree if detached
                        } catch (e) {
                            try {
                                pythonProcess.kill('SIGINT');
                            } catch(e2) {}
                        }
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
        // Python is managed by PM2, nothing to kill
    });
}
