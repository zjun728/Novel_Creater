@echo off
echo backend bat started > D:\Projects\Novel_Creater\tmp\backend_bat_started.txt
cd /d D:\Projects\Novel_Creater\backend
"D:\Software\Python\Python312\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 > D:\Projects\Novel_Creater\backend\uvicorn.manual.log 2>&1
pause
