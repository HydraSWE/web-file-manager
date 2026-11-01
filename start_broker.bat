@echo off
setlocal
title HYDRA Windows Security Broker
cd /d "%~dp0"

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if %errorlevel% equ 0 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo [ERROR] Python not found in system PATH.
    pause
    exit /b 1
)

echo ========================================================
echo   HYDRA Windows Authentication Broker
echo   Provides native Windows Hello & CredUI authentication
echo ========================================================
echo.

"%PYTHON_EXE%" local_broker\broker.py
pause
