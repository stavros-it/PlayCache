@echo off
setlocal

REM ============================================================
REM  PlayCache - Create desktop shortcut for the current user
REM  Run this file (double-click or from a terminal) to create
REM  a PlayCache.lnk shortcut on your Desktop.
REM ============================================================

REM --- Resolve the directory this .bat lives in (project root) ---
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "TARGET=%PROJECT_DIR%\run.pyw"
set "ICON=%PROJECT_DIR%\playcache\assets\app.ico"
set "SHORTCUT=%USERPROFILE%\Desktop\PlayCache.lnk"

REM --- Validate required files exist ---
if not exist "%TARGET%" (
    echo ERROR: run.pyw not found at:
    echo   %TARGET%
    echo Make sure this .bat file is in the PlayCache project root.
    pause
    exit /b 1
)
if not exist "%ICON%" (
    echo ERROR: app.ico not found at:
    echo   %ICON%
    echo Run "python scripts\make_icon.py" first to generate the icon.
    pause
    exit /b 1
)

REM --- Create the shortcut via PowerShell (WScript.Shell COM) ---
echo Creating desktop shortcut:
echo   Target : %TARGET%
echo   Icon   : %ICON%
echo   Output : %SHORTCUT%

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$lnk = $ws.CreateShortcut('%SHORTCUT%');" ^
    "$lnk.TargetPath = '%TARGET%';" ^
    "$lnk.WorkingDirectory = '%PROJECT_DIR%';" ^
    "$lnk.IconLocation = '%ICON%, 0';" ^
    "$lnk.Description = 'PlayCache - game catalog';" ^
    "$lnk.WindowStyle = 7;" ^
    "$lnk.Save();"

if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to create shortcut ^(PowerShell returned error %ERRORLEVEL%^).
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo SUCCESS: Shortcut created on your Desktop.
pause
endlocal
