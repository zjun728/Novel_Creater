@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting Novel Creator backend...
echo URL: http://127.0.0.1:8000/api/health
echo.

set "PYTHON_EXE=D:\Software\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
) else (
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
)

echo.
echo Backend process exited.
pause
