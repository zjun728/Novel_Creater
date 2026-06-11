import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'

const isDirectRun = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href

if (isDirectRun) {
  const target = fileURLToPath(new URL('./run_realistic_longform_flow_fixed.mjs', import.meta.url))
  const child = spawn(process.execPath, [
    target,
    ...process.argv.slice(2)
  ], {
    stdio: 'inherit',
    windowsHide: true
  })

  child.on('exit', code => {
    process.exitCode = code ?? 1
  })
}
