# Optional live smoke uses existing local DPAPI credentials. Never prints secrets.
param([switch]$LiveLLM)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousKey = $env:OPENAI_API_KEY
$previousModel = $env:OPENAI_MODEL
$settings = $null
try {
    $acceptanceArguments = @((Join-Path $PSScriptRoot 'retrieval-iteration-acceptance.py'))
    if ($LiveLLM) {
        . (Join-Path $PSScriptRoot 'openai-settings.ps1')
        $settings = Read-AgentOpenAISettings -Path (Join-Path $env:LOCALAPPDATA 'OwnDataAgent/openai.json')
        $env:OPENAI_API_KEY = $settings.Key
        $env:OPENAI_MODEL = $settings.Model
        $acceptanceArguments += '--live-llm'
    }
    & (Join-Path $projectRoot '.venv/Scripts/python.exe') @acceptanceArguments
} finally {
    $env:OPENAI_API_KEY = $previousKey
    $env:OPENAI_MODEL = $previousModel
    if ($settings) { $settings.Key = $null }
}
