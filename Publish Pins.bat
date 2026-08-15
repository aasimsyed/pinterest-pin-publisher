@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python scripts\publish.py
) else (
    python3 scripts\publish.py
)
echo.
pause
