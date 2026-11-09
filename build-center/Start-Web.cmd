@echo off
cd /d "%~dp0"
if exist "%~dp0SukiSU-Build-Center.exe" (
  start "" "%~dp0SukiSU-Build-Center.exe" --web
  exit /b
)
python desktop.py --web
if errorlevel 1 pause
