@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting Novel Creator frontend...
echo URL: http://127.0.0.1:5173/
echo.

set "NPM_EXE=D:\Software\nodejs\npm.cmd"

if exist "%NPM_EXE%" (
  "%NPM_EXE%" --prefix frontend run dev -- --host 127.0.0.1
) else (
  npm.cmd --prefix frontend run dev -- --host 127.0.0.1
)

echo.
echo Frontend process exited.
pause
