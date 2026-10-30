@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ========================================================
    echo   Requesting Administrator Privileges...
    echo   Please click "YES" on the Windows UAC confirmation.
    echo ========================================================
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ========================================================
echo   Setting Network Connection to Private Profile
echo ========================================================

powershell -NoProfile -Command "Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private"

echo.
echo ========================================================
echo   [SUCCESS] Network profile is now set to Private!
echo   Local Wi-Fi devices (smartphones/tablets) can now connect.
echo ========================================================
echo.
timeout /t 5
