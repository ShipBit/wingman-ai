param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 49111
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $repoRoot '.venv-core/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $corePython)) {
    throw 'Core environment is missing. Follow docs/elite-dangerous.md to create .venv-core and install requirements.txt.'
}

# Do not stop or replace an existing Core process.
$probe = New-Object System.Net.Sockets.TcpClient
$occupied = $false
try {
    $probe.Connect('127.0.0.1', $Port)
    $occupied = $true
} catch [System.Net.Sockets.SocketException] {
    # A refused connection means the port is available.
    if ($_.Exception.SocketErrorCode -ne [System.Net.Sockets.SocketError]::ConnectionRefused) {
        throw
    }
} finally {
    $probe.Dispose()
}
if ($occupied) {
    throw "Port $Port is already in use. Connect to the running Core or close it yourself before starting this checkout."
}

Push-Location $repoRoot
try {
    # Client mode lets the GUI handle missing account/provider credentials.
    & $corePython main.py --host 127.0.0.1 --port $Port --sidecar
    if ($LASTEXITCODE -ne 0) {
        throw "Wingman Core exited with code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
