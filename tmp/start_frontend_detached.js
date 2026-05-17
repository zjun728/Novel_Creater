const fs = require('fs');
const { spawn } = require('child_process');

const logPath = 'D:\\Projects\\Novel_Creater\\frontend\\vite.spawn.log';
const out = fs.openSync(logPath, 'a');

const child = spawn(
  'D:\\Software\\nodejs\\node.exe',
  ['node_modules\\vite\\bin\\vite.js', '--host', '127.0.0.1'],
  {
    cwd: 'D:\\Projects\\Novel_Creater\\frontend',
    detached: true,
    stdio: ['ignore', out, out],
    shell: false
  }
);

child.unref();
console.log(child.pid);
