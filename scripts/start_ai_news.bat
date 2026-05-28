@echo off
REM 启动 AI_NEWS（后端 + 内嵌微信守护进程）。
REM
REM 双击直接运行；或丢进 shell:startup 实现 Windows 开机自启。
REM
REM 自启用法：
REM   1. Win+R → shell:startup → 回车（打开 Windows 启动文件夹）
REM   2. 把本文件的快捷方式（不是文件本身）拖进去
REM   3. 下次开机会自动启动后端
REM
REM 永循环：uvicorn 退出后自动重启（用于微信里发"重启"指令的自我重启）。
REM 想真正停掉：在黑窗口里连按两次 Ctrl+C（第一次中断 uvicorn，第二次跳出 .bat 循环）。

setlocal enabledelayedexpansion

REM ── 项目根目录（如果以后挪了路径只改这里） ──────────────────────────────
set "PROJECT_DIR=c:\Users\wangzy\Desktop\hobby\AI_NEWS"

REM ── 日志目录（确保存在） ────────────────────────────────────────────────
set "LOG_DIR=%PROJECT_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM ── 进入项目 + 用 venv 的 python 跑 uvicorn ─────────────────────────────
cd /d "%PROJECT_DIR%"

if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

:loop
echo. >> "%LOG_DIR%\start.log"
echo [%date% %time%] starting AI_NEWS uvicorn... >> "%LOG_DIR%\start.log"
"%PY%" -m uvicorn api.main:app --port 8000 2>> "%LOG_DIR%\start.log"

REM uvicorn 退出码：0 = 正常退出（"重启"指令触发）；非 0 = 崩溃
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] uvicorn exited code=%EXIT_CODE% >> "%LOG_DIR%\start.log"

if "%EXIT_CODE%"=="0" (
    echo Restarting in 3 seconds...
    timeout /t 3 /nobreak >nul
    goto loop
)

REM 非 0 退出 = 崩溃，给个 10 秒回看时间再重启，避免无限崩溃循环吃 CPU
echo Crashed with code %EXIT_CODE%, restart in 10 seconds...
timeout /t 10 /nobreak >nul
goto loop

endlocal
