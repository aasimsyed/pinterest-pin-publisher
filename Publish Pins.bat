@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python scripts\publish.py --menu
) else (
    python3 scripts\publish.py --menu
)
echo.
pause
