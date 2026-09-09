@echo off
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    where python3 >nul 2>nul
    if %errorlevel% neq 0 (
        echo Python isn't installed yet.
        where winget >nul 2>nul
        if %errorlevel%==0 (
            echo Installing Python with winget...
            winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
            echo If the next step still says python isn't found, close this window and double-click Setup again.
        ) else (
            echo Opening the Python download page -- install it, then double-click Setup again.
            start https://www.python.org/downloads/
            pause
            exit /b 1
        )
    )
)

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo Node.js isn't installed yet.
    where winget >nul 2>nul
    if %errorlevel%==0 (
        echo Installing Node.js with winget...
        winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
        echo If the next step still says node isn't found, close this window and double-click Setup again.
    ) else (
        echo Opening the Node.js download page -- install it, then double-click Setup again.
        start https://nodejs.org/
        pause
        exit /b 1
    )
)

where python >nul 2>nul
if %errorlevel%==0 (
    python scripts\setup.py
) else (
    python3 scripts\setup.py
)
echo.
pause
