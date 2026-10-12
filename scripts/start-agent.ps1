# Load the existing per-user encrypted credential without printing it.
param(
    [Parameter(Mandatory=$true)][string]$Question,
    [switch]$MultiPlan,
    [int]$MaxSteps = 8,
    [int]$MaxSearches = 3,
    [string]$Model
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'openai-settings.ps1')
$settingsPath = Join-Path $env:LOCALAPPDATA 'OwnDataAgent/openai.json'
$settings = Read-AgentOpenAISettings -Path $settingsPath
if (-not $Model) { $Model = $settings.Model }
$previousKey = $env:OPENAI_API_KEY
$previousModel = $env:OPENAI_MODEL
try {
    $env:OPENAI_API_KEY = $settings.Key
    $env:OPENAI_MODEL = $Model
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $agentArguments = @('-m', 'local_agent.cli', 'agent', $Question,
        '--max-steps', $MaxSteps, '--max-searches', $MaxSearches)
    if ($MultiPlan) { $agentArguments += '--multi-plan' }
    & (Join-Path $projectRoot '.venv/Scripts/python.exe') @agentArguments
} finally {
    $env:OPENAI_API_KEY = $previousKey
    $env:OPENAI_MODEL = $previousModel
    $settings.Key = $null
}
