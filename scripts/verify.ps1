# 接入数据后重跑验收；质量证据超过24小时需要先重新dbt build。
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& .venv/Scripts/python.exe -m pip check
if ($LASTEXITCODE) { throw 'Dependency check failed' }
& .venv/Scripts/python.exe -m pytest --junitxml=docs/own-agent-tests.xml
if ($LASTEXITCODE) { throw 'Tests failed' }
