# 单独的数据开发环境；不把dbt及其传递依赖安装到Agent运行环境。
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not (Test-Path -LiteralPath .warehouse-venv/Scripts/dbt.exe)) {
    python -m venv .warehouse-venv
    if ($LASTEXITCODE) { throw 'Warehouse environment failed' }
    & .warehouse-venv/Scripts/python.exe -m pip install -r requirements-warehouse.txt
    if ($LASTEXITCODE) { throw 'Warehouse dependencies failed' }
}
& .warehouse-venv/Scripts/dbt.exe build --project-dir warehouse-commerce --profiles-dir warehouse-commerce
if ($LASTEXITCODE) { throw 'Warehouse build failed' }
Copy-Item -LiteralPath warehouse-commerce/target/run_results.json -Destination docs/thelook-dbt-run-results.json
& .warehouse-venv/Scripts/dbt.exe docs generate --project-dir warehouse-commerce --profiles-dir warehouse-commerce
if ($LASTEXITCODE) { throw 'Warehouse catalog generation failed' }
& .venv/Scripts/python.exe -m local_agent.cli publish
if ($LASTEXITCODE) { throw 'Snapshot publication failed' }
