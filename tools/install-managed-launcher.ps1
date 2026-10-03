param([switch]$Restore, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$python = Join-Path $repo '.venv-core/Scripts/pythonw.exe'
$launcher = Join-Path $repo 'tools/managed_launch.py'
$state = Join-Path $repo '.elite-local/managed-launch'
$receipt = Join-Path $state 'shortcuts.json'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $launcher)) {
    throw 'The managed Core environment or launcher is missing.'
}
$shell = New-Object -ComObject WScript.Shell
$roots = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('CommonDesktopDirectory'),
    [Environment]::GetFolderPath('Programs'),
    [Environment]::GetFolderPath('CommonPrograms'),
    (Join-Path $env:APPDATA 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar')
)
if ($Restore) {
    $entries = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
    foreach ($entry in $entries) {
        $current = $shell.CreateShortcut($entry.path)
        if ($current.TargetPath -eq $python -and $current.Arguments -eq ('"' + $launcher + '"')) {
            if (-not $CheckOnly) { Copy-Item -LiteralPath $entry.backup -Destination $entry.path -Force }
        }
    }
    return
}
$existing = @()
if (Test-Path -LiteralPath $receipt) { $existing = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json }
if (-not $CheckOnly) {
    foreach ($entry in $existing) {
        $current = $shell.CreateShortcut($entry.path)
        if ($current.TargetPath -eq $python -and $current.Arguments -eq ('"' + $launcher + '"')) {
            $original = $shell.CreateShortcut($entry.backup)
            $current.IconLocation = if ($original.IconLocation -and $original.IconLocation -ne ',0') { $original.IconLocation } else { $original.TargetPath + ',0' }
            $current.Save()
        }
    }
}
$found = @($roots | Select-Object -Unique | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
    Get-ChildItem -LiteralPath $_ -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue
} | ForEach-Object {
    $link = $shell.CreateShortcut($_.FullName)
    if ([IO.Path]::GetFileName($link.TargetPath) -eq 'WingmanAI.exe') { $_ }
})
if ($CheckOnly) {
    [PSCustomObject]@{ MatchingShortcuts=$found.Count; AlreadyManaged=$existing.Count; Launcher=$launcher }
    return
}
if ($found.Count -eq 0 -and $existing.Count -eq 0) { throw 'No Wingman shortcut was found to install the managed launcher.' }
New-Item -ItemType Directory -Path $state -Force | Out-Null
$changed = @()
try {
    foreach ($file in $found) {
        $backup = Join-Path $state ([Guid]::NewGuid().ToString() + '.lnk')
        Copy-Item -LiteralPath $file.FullName -Destination $backup
        $entry = [PSCustomObject]@{ path=$file.FullName; backup=$backup }
        $link = $shell.CreateShortcut($file.FullName)
        $originalIcon = if ($link.IconLocation -and $link.IconLocation -ne ',0') { $link.IconLocation } else { $link.TargetPath + ',0' }
        $link.TargetPath = $python
        $link.IconLocation = $originalIcon
        $link.Arguments = '"' + $launcher + '"'
        $link.WorkingDirectory = $repo
        $link.WindowStyle = 7
        $link.Description = 'Wingman AI with automatic Elite companion and audio recovery'
        $link.Save()
        $changed += $entry
    }
    @($existing + $changed) | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $receipt -Encoding UTF8
} catch {
    foreach ($entry in $changed) { Copy-Item -LiteralPath $entry.backup -Destination $entry.path -Force }
    throw
}
[PSCustomObject]@{ Updated=$changed.Count; RestoreCommand='tools/install-managed-launcher.ps1 -Restore' }
