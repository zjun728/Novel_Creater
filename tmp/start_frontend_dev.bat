@echo off
echo frontend bat started > D:\Projects\Novel_Creater\tmp\frontend_bat_started.txt
cd /d D:\Projects\Novel_Creater
"D:\Software\nodejs\npm.cmd" --prefix frontend run dev -- --host 127.0.0.1 > D:\Projects\Novel_Creater\frontend\vite.manual.log 2>&1
pause
