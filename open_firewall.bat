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

set PORT=8080
if defined PORT_OVERRIDE set PORT=%PORT_OVERRIDE%
set RULE_NAME=Web_File_Manager_Port_%PORT%

echo ========================================================
echo   Adding Windows Defender Firewall Rule for Port %PORT%
echo ========================================================

netsh advfirewall firewall delete rule name="%RULE_NAME%" >nul 2>&1
netsh advfirewall firewall add rule name="%RULE_NAME%" dir=in action=allow protocol=TCP localport=%PORT% profile=private,public

echo.
echo ========================================================
echo   [SUCCESS] Firewall rule active for port %PORT%!
echo   Local Wi-Fi devices can now connect to this server.
echo ========================================================
echo.
timeout /t 3
