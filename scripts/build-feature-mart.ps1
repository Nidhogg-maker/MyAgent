param(
    [string]$AsOf = '2026-10-11',
    [switch]$VerifyRepeat
)
# Dedicated deterministic write path; the Agent query service remains read-only.
$ErrorActionPreference = 'Stop'
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectDirectory
$buildArguments = @('-m', 'local_agent.feature_pipeline', '--as-of', $AsOf)
if ($VerifyRepeat) { $buildArguments += '--verify-repeat' }
& (Join-Path $projectDirectory '.venv/Scripts/python.exe') @buildArguments
if ($LASTEXITCODE -ne 0) { throw 'Feature data product build failed; active release was not switched.' }
