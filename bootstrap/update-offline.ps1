# Run ONLY after exiting Tenmiyora from the tray.
# Example: powershell -NoProfile -File bootstrap/update-offline.ps1 -Package X -Live Y -Backup Z -Approve
param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$Live,
    [Parameter(Mandatory=$true)][string]$Backup,
    [switch]$Approve
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtime = Join-Path $root '.runtime'
$lock = $null
try {
    if (-not $Approve) { throw 'Explicit -Approve required. No changes made.' }
    if (-not (Test-Path -LiteralPath $runtime -PathType Container)) {
        throw 'Runtime directory unavailable; start and stop Tenmiyora first.'
    }
    # Same lock file as launch.ps1: refuse to update while launcher is alive.
    try {
        $lock = [IO.File]::Open((Join-Path $runtime 'launcher.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    } catch [IO.IOException] {
        throw 'Launcher is still active. Exit Tenmiyora from the tray first.'
    }
    $python = Join-Path $runtime 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $command = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw 'Python is unavailable.' }
        $python = $command.Source
    }
    $argsList = @('-I','-X','utf8',(Join-Path $PSScriptRoot 'windows_offline_update.py'),
        '--root',$root,'--package',$Package,'--live',$Live,'--backup',$Backup,'--approve')
    & $python @argsList
    if ($LASTEXITCODE -ne 0) { throw 'Offline installation rejected or failed. See diagnostic above.' }
    Write-Host 'Package installed. Restart Tenmiyora manually with Tenmiyora.bat.'
} finally {
    if ($lock) { $lock.Dispose() }
}
