@echo off
REM 启动 AI_NEWS（后端 + 内嵌微信守护进程）
REM
REM 双击直接运行；或丢进 shell:startup 实现 Windows 开机自启。
REM
REM 自启用法：
REM   1. Win+R → shell:startup → 回车（打开 Windows 启动文件夹）
REM   2. 把本文件的快捷方式（不是文件本身）拖进去
REM   3. 下次开机会自动启动后端
REM
REM 想看日志：把 PROJECT_DIR\logs\start.log 翻一翻
REM 想停掉：找到那个黑窗口，按 Ctrl+C 或直接 ×

setlocal

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

echo [%date% %time%] starting AI_NEWS uvicorn... >> "%LOG_DIR%\start.log"
"%PY%" -m uvicorn api.main:app --port 8000 2>> "%LOG_DIR%\start.log"

endlocal
