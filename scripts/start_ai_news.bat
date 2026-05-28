@echo off
REM Launch AI_NEWS backend + embedded WeChat (iLink) daemon.
REM
REM Usage: double-click this file, OR put a shortcut into shell:startup
REM        for Windows boot-time auto-start.
REM
REM Infinite-loop wrapper: when uvicorn exits, this script automatically
REM restarts it. This is required for the WeChat "restart" command to
REM work end-to-end (process exits cleanly, then the loop respawns it).
REM
REM To truly STOP: press Ctrl+C twice. First press kills uvicorn,
REM second press breaks out of this batch loop.

setlocal enabledelayedexpansion

REM Mark this process as 'started via the bat loop' so dispatcher.py
REM knows that os._exit(0) will be safely caught by the outer loop.
set "AI_NEWS_BAT_LOOP=1"

REM Window title — easier to identify among many cmd windows.
title AI_NEWS

REM Project root — change here if you move the repo.
set "PROJECT_DIR=c:\Users\wangzy\Desktop\hobby\AI_NEWS"

REM Log dir
set "LOG_DIR=%PROJECT_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%PROJECT_DIR%"

REM Prefer venv python if available
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

:loop
echo. >> "%LOG_DIR%\start.log"
echo [%date% %time%] starting AI_NEWS uvicorn... >> "%LOG_DIR%\start.log"
echo.
echo ================================================================
echo  AI_NEWS uvicorn starting at %date% %time%
echo ================================================================
"%PY%" -m uvicorn api.main:app --port 8000 2>> "%LOG_DIR%\start.log"

set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] uvicorn exited code=%EXIT_CODE% >> "%LOG_DIR%\start.log"

echo.
echo ================================================================
echo  uvicorn exited with code %EXIT_CODE% at %date% %time%
echo ================================================================

if "%EXIT_CODE%"=="0" (
    echo Clean exit ^(restart triggered^). Respawning in 3 seconds...
    timeout /t 3 /nobreak >nul
    goto loop
)

echo Crash exit. Respawning in 10 seconds to avoid tight crash loop...
timeout /t 10 /nobreak >nul
goto loop

endlocal
