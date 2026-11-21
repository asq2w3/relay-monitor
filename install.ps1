$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command python -ErrorAction SilentlyContinue) {
    python "$RepoDir\install.py"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    python3 "$RepoDir\install.py"
} else {
    Write-Host "❌ 未检测到 Python 3，请先从 https://www.python.org/downloads/ 或 Microsoft Store 安装 Python 3。" -ForegroundColor Red
    exit 1
}
