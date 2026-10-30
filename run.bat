@echo off
setlocal
cd /d "%~dp0"

if defined APP_NAME (
    title %APP_NAME%
) else (
    title Web File Manager
)

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if %errorlevel% equ 0 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo [ERROR] Python is not installed or not found in system PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo ========================================================
echo   Web File Manager
echo   Using Python: %PYTHON_EXE%
echo ========================================================
echo.

"%PYTHON_EXE%" -c "import fastapi, uvicorn, qrcode, multipart" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing required dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    echo.
)

"%PYTHON_EXE%" server.py

if %errorlevel% neq 0 (
    echo.
    echo Server stopped with exit code %errorlevel%.
)
pause
