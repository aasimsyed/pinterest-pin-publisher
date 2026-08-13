@echo off
title Pin Publisher - one-time install
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python is not installed. Get it from https://www.python.org/downloads/
  echo  IMPORTANT: tick "Add python.exe to PATH" on the first screen.
  echo  Then run this again.
  echo.
  pause
  exit /b
)
py -m pip install -r "%~dp0..\requirements.txt"
echo.
echo Done! From now on, double-click:  Publish Pins.bat
pause
