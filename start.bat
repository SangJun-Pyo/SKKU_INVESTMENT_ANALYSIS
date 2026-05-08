@echo off
cd /d %~dp0
echo MarkovPortfolio V4
echo http://127.0.0.1:8000
echo.
uvicorn main:app --host 127.0.0.1 --port 8000
pause
