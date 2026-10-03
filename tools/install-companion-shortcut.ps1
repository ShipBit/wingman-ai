param([switch]$Restore, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$python = Join-Path $repo '.venv-core/Scripts/pythonw.exe'
$launcher = Join-Path $repo 'tools/managed_launch.py'
$state = Join-Path $repo '.elite-local/managed-launch'
$receipt = Join-Path $state 'companion-shortcut.json'
$desktop = [Environment]::GetFolderPath('Desktop')
$target = [IO.Path]::GetFullPath((Join-Path $desktop 'Elite Companion - Managed Core.lnk'))
if ((Split-Path -Parent $target) -ne [IO.Path]::GetFullPath($desktop)) { throw 'Invalid shortcut destination.' }
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $launcher)) {
    throw 'The managed Core environment or launcher is missing.'
}
$shell = New-Object -ComObject WScript.Shell
$exists = Test-Path -LiteralPath $target
$matches = $false
if ($exists) {
    $link = $shell.CreateShortcut($target)
    $matches = $link.TargetPath -eq $python -and $link.Arguments -eq ('"' + $launcher + '"') -and $link.WorkingDirectory -eq $repo
}
if ($CheckOnly) {
    [PSCustomObject]@{ Shortcut=$target; Exists=$exists; Matches=$matches; Drift=($exists -and -not $matches) }
    return
}
if ($Restore) {
    $saved = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
    if ($saved.path -ne $target -or -not $matches -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $saved.sha256) {
        throw 'Shortcut changed after installation; automatic restore stopped.'
    }
    Remove-Item -LiteralPath $target
    return
}
if ($exists) {
    if (-not $matches) { throw 'Companion shortcut drift detected. Preserve/review the existing shortcut before reinstalling.' }
    return
}
New-Item -ItemType Directory -Path $state -Force | Out-Null
$link = $shell.CreateShortcut($target)
$link.TargetPath = $python
$link.Arguments = '"' + $launcher + '"'
$link.WorkingDirectory = $repo
$link.WindowStyle = 7
$link.IconLocation = (Join-Path $env:ProgramFiles 'WingmanAI/WingmanAI.exe') + ',0'
$link.Description = 'Elite Companion: managed source Core and installed Wingman GUI; acceptance pending'
$link.Save()
[PSCustomObject]@{ path=$target; sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash } |
    ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
[PSCustomObject]@{ Created=$target; RestoreCommand='tools/install-companion-shortcut.ps1 -Restore' }
