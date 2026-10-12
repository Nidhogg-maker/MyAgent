# 独立输入窗口：先运行命令，再去网页复制密钥，回到窗口粘贴即可。
param([string]$Model = 'gpt-6.1-sol', [switch]$FromClipboard)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'openai-settings.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'OpenAI 配置'
$form.ClientSize = New-Object Drawing.Size(560, 235)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$label = New-Object Windows.Forms.Label
$label.Text = '现在去 OpenAI 页面复制密钥，再回到下方输入框粘贴。'
$label.Location = New-Object Drawing.Point(18, 18)
$label.Size = New-Object Drawing.Size(520, 25)
$form.Controls.Add($label)
$keyBox = New-Object Windows.Forms.TextBox
$keyBox.Location = New-Object Drawing.Point(18, 50)
$keyBox.Size = New-Object Drawing.Size(520, 28)
$keyBox.UseSystemPasswordChar = $true
$form.Controls.Add($keyBox)
$modelLabel = New-Object Windows.Forms.Label
$modelLabel.Text = 'API 模型'
$modelLabel.Location = New-Object Drawing.Point(18, 95)
$form.Controls.Add($modelLabel)
$modelBox = New-Object Windows.Forms.TextBox
$modelBox.Text = $Model
$modelBox.Location = New-Object Drawing.Point(120, 92)
$modelBox.Size = New-Object Drawing.Size(418, 28)
$form.Controls.Add($modelBox)
$statusLabel = New-Object Windows.Forms.Label
$statusLabel.Text = '密钥将加密保存在本机当前用户目录，不显示或写入明文。'
$statusLabel.Location = New-Object Drawing.Point(18, 132)
$statusLabel.Size = New-Object Drawing.Size(520, 40)
$form.Controls.Add($statusLabel)
$saveButton = New-Object Windows.Forms.Button
$saveButton.Text = '保存配置'
$saveButton.Location = New-Object Drawing.Point(418, 182)
$saveButton.Size = New-Object Drawing.Size(120, 32)
$form.Controls.Add($saveButton)
$form.AcceptButton = $saveButton
$form.Tag = $false
$settingsPath = Join-Path $env:LOCALAPPDATA 'OwnDataAgent/openai.json'
$saveButton.Add_Click({
    try {
        Save-AgentOpenAISettings -Key $keyBox.Text -Model $modelBox.Text -Path $settingsPath
        $keyBox.Clear()
        $form.Tag = $true
        $form.Close()
    } catch { $statusLabel.Text = $_.Exception.Message }
})
try {
    [void]$form.ShowDialog()
    if ($form.Tag) { Write-Host '配置已加密保存。现在运行 start-openai.ps1 即可。' }
    else { Write-Host '已取消，原配置未变更。' }
} finally { $keyBox.Clear(); $form.Dispose() }
