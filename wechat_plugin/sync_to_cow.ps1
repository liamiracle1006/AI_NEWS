# 把本目录的插件代码同步到 CoW 项目，方便迭代开发。
# 不会覆盖 CoW 那边的 config.json（用户配置），只同步 .py 和 .template / README。

$ErrorActionPreference = "Stop"

$src = $PSScriptRoot
$dst = "c:\Users\wangzy\Desktop\hobby\chatgpt-on-wechat\plugins\ai_news"

if (-not (Test-Path $dst)) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
}

# 只同步源代码和模板，跳过本地 config.json 和 sync 脚本自身
$files = @(
    "__init__.py",
    "ai_news.py",
    "intent_parser.py",
    "formatter.py",
    "renderer.py",
    "scheduler.py",
    "config.json.template",
    "README.md"
)

foreach ($f in $files) {
    $srcFile = Join-Path $src $f
    $dstFile = Join-Path $dst $f
    if (Test-Path $srcFile) {
        Copy-Item $srcFile $dstFile -Force
        Write-Host "synced $f"
    }
}

Write-Host ""
Write-Host "Done. Restart CoW (python app.py) to load changes." -ForegroundColor Green
