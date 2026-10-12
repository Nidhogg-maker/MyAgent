# 自动读取 DPAPI 加密配置；启动后恢复原有环境。
param([string]$Model, [string]$Question = '2026年9月订单数是多少', [switch]$Chat, [string]$Session)
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
    if ($Chat) {
        if ($Session) { & "$projectRoot/.venv/Scripts/python.exe" -m local_agent.cli --intent-mode llm chat --session $Session }
        else { & "$projectRoot/.venv/Scripts/python.exe" -m local_agent.cli --intent-mode llm chat }
    } else {
        & "$projectRoot/.venv/Scripts/python.exe" -m local_agent.cli --intent-mode llm ask $Question
    }
} finally {
    $env:OPENAI_API_KEY = $previousKey
    $env:OPENAI_MODEL = $previousModel
    $settings.Key = $null
}
