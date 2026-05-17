const fs = require('fs');
const { spawn } = require('child_process');

const logPath = 'D:\\Projects\\Novel_Creater\\frontend\\vite.wrapper.log';
const out = fs.openSync(logPath, 'a');

const vite = spawn(
  'D:\\Software\\nodejs\\node.exe',
  ['node_modules\\vite\\bin\\vite.js', '--host', '127.0.0.1'],
  {
    cwd: 'D:\\Projects\\Novel_Creater\\frontend',
    stdio: ['pipe', out, out]
  }
);

vite.stdin.write('\n');
setInterval(() => {
  if (!vite.killed) {
    vite.stdin.write('\n');
  }
}, 30000);

vite.on('exit', (code, signal) => {
  fs.writeSync(out, `\n[vite exited] code=${code} signal=${signal}\n`);
  process.exit(code || 0);
});

process.on('exit', () => {
  if (!vite.killed) vite.kill();
});

setInterval(() => {}, 1 << 30);
