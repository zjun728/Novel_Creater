import { defineConfig } from '@playwright/test'

function shellQuoteExecutable(executable: string): string {
  if (!executable) throw new Error('PYTHON must name an executable')
  if (process.platform === 'win32') {
    if (/["\r\n&|<>^%!]/.test(executable)) {
      throw new Error('PYTHON contains unsafe Windows shell characters')
    }
    return `"${executable}"`
  }
  return `'${executable.replaceAll("'", "'\"'\"'")}'`
}

const python = process.env.PYTHON || 'python'
const pythonExecutable = shellQuoteExecutable(python)

export default defineConfig({
  testDir: './e2e',
  outputDir: '../output/playwright/test-results',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `${pythonExecutable} -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: false,
    },
    {
      command: 'npm --prefix frontend run dev -- --port 5173',
      cwd: '..',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
    },
  ],
})
