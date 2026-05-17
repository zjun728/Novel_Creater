const { spawn } = require('child_process');

const child = spawn(
  'D:\\Software\\nodejs\\node.exe',
  ['D:\\Projects\\Novel_Creater\\tmp\\run_frontend_server.js'],
  {
    cwd: 'D:\\Projects\\Novel_Creater',
    detached: true,
    stdio: 'ignore'
  }
);

child.unref();
console.log(child.pid);
