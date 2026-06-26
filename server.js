const { spawn } = require('child_process');
const path = require('path');

console.log("Starting Python Backend wrapper...");

const pythonExe = path.join(__dirname, 'venv', 'Scripts', 'pythonw.exe');
const pyProc = spawn(pythonExe, ['main.py'], {
    cwd: __dirname,
    stdio: 'inherit',
    windowsHide: true
});

pyProc.on('close', (code) => {
    console.log(`Python process exited with code ${code}`);
    process.exit(code);
});
