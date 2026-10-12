# 从本项目目录独立安装；不需要相邻的三个上游仓库。
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
python -m venv .venv
if ($LASTEXITCODE) { throw 'Create environment failed' }
& .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& .venv/Scripts/python.exe -m pip install -e . --no-deps
if ($LASTEXITCODE) { throw 'Project installation failed' }
