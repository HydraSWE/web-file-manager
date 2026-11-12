@echo off
setlocal
cd /d "%~dp0"

if defined APP_NAME (
    title %APP_NAME%
) else (
    title Hydra Web File Manager
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
echo   Hydra Web File Manager & Windows Security
echo   Using Python: %PYTHON_EXE%
echo ========================================================
echo.

:: 1. Self-healing configuration template check
if not exist "%~dp0config.json" (
    if exist "%~dp0config.example.json" (
        echo [HYDRA] First-time setup: Initializing config.json from template...
        copy "%~dp0config.example.json" "%~dp0config.json" >nul
        if %errorlevel% equ 0 (
            echo [HYDRA] Successfully created config.json with safe defaults.
        )
    )
)

:: 2. Pre-flight dependency check & binary-preferred installation
"%PYTHON_EXE%" -c "import fastapi, uvicorn, qrcode, multipart, cryptography, argon2, aiofiles" >nul 2>&1
if %errorlevel% neq 0 (
    echo [HYDRA] Missing dependencies detected. Installing required packages...
    "%PYTHON_EXE%" -m pip install --prefer-binary -r requirements.txt
    if %errorlevel% neq 0 (
        echo [HYDRA] Warning: Retrying with pre-compiled binary-only fallback...
        "%PYTHON_EXE%" -m pip install --only-binary :all: -r requirements.txt
    )
    "%PYTHON_EXE%" -c "import fastapi, uvicorn, qrcode, multipart, cryptography, argon2, aiofiles" >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo ========================================================
        echo [ERROR] Failed to install required dependencies.
        echo Please ensure your internet connection is active.
        echo You can try installing manually by running:
        echo   pip install --prefer-binary -r requirements.txt
        echo ========================================================
        echo.
        pause
        exit /b 1
    )
    echo [HYDRA] Dependencies verified successfully.
    echo.
)

echo [HYDRA] Starting server and local Windows Auth Broker...
"%PYTHON_EXE%" server.py

if %errorlevel% neq 0 (
    echo.
    echo Server stopped with exit code %errorlevel%.
)
pause
