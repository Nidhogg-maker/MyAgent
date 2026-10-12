# 公共配置函数：直接使用 DPAPI 字节加密，绕开 SecureString 转换链路。
Add-Type -AssemblyName System.Security
function Save-AgentOpenAISettings {
    param([string]$Key, [string]$Model, [string]$Path)
    $normalizedKey = $Key.Trim()
    if (-not $normalizedKey.StartsWith('sk-') -or $normalizedKey.Length -lt 20 -or $normalizedKey -match '\s') {
        throw '输入内容不是完整 API Key。请在窗口中粘贴密钥；配置未更新。'
    }
    if ([string]::IsNullOrWhiteSpace($Model)) { throw '模型名称不能为空' }
    $keyBytes = [Text.Encoding]::UTF8.GetBytes($normalizedKey)
    try {
        $encrypted = [Security.Cryptography.ProtectedData]::Protect($keyBytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $roundtrip = [Security.Cryptography.ProtectedData]::Unprotect($encrypted, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        try {
            if ([Convert]::ToBase64String($keyBytes) -cne [Convert]::ToBase64String($roundtrip)) { throw '加密验证失败，未保存' }
        } finally { [Array]::Clear($roundtrip, 0, $roundtrip.Length) }
        $settings = @{ version = 2; model = $Model.Trim(); dpapi_key = [Convert]::ToBase64String($encrypted) }
        $directory = Split-Path -Parent $Path
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $temporaryPath = $Path + '.tmp'
        [IO.File]::WriteAllText($temporaryPath, ($settings | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    } finally { [Array]::Clear($keyBytes, 0, $keyBytes.Length); $normalizedKey = $null }
}
function Read-AgentOpenAISettings {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw '请先运行 configure-openai.ps1，在窗口中保存配置。' }
    $settings = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($settings.version -ne 2) { throw '检测到旧配置，请运行 configure-openai.ps1 重新保存。' }
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($settings.dpapi_key), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    try { return @{ Key = [Text.Encoding]::UTF8.GetString($bytes); Model = $settings.model } }
    finally { [Array]::Clear($bytes, 0, $bytes.Length) }
}
