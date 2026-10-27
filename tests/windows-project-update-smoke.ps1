$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$base=Join-Path $env:TEMP ('tenmiyora-full-update-'+[guid]::NewGuid().ToString('N'))
$hostRoot=Join-Path $base 'host'
$old=$null
try {
    New-Item -ItemType Directory -Path $hostRoot -Force | Out-Null
    foreach ($part in @('Tenmiyora.bat','bootstrap','web')) {
        Copy-Item -LiteralPath (Join-Path $repo $part) -Destination $hostRoot -Recurse -Force
    }
    & python (Join-Path $repo 'tests/prepare_update_smoke.py') $base
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare test package' }
    $old=Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c',('"' + (Join-Path $hostRoot 'Tenmiyora.bat') + '" --no-browser --console')) -PassThru -WindowStyle Hidden
    $session=Join-Path $hostRoot '.runtime/session.json'
    $ready=$false
    for ($i=0;$i -lt 120;$i++) {
        if (Test-Path -LiteralPath $session) {
            try {
                $state=Get-Content -LiteralPath $session -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($state.app -eq 'Tenmiyora' -and $state.url -match '^http://127\.0\.0\.1:[0-9]+$') {
                    $res=Invoke-RestMethod -Uri ($state.url+'/health') -TimeoutSec 2 -Headers @{'X-Tenmiyora-Token'=[string]$state.token}
                    if ($res.pid -eq $state.pid -and $res.app -eq 'Tenmiyora') { $ready=$true;break }
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) { throw 'Original launcher never became healthy' }
    $package=Join-Path $base 'package'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $hostRoot 'bootstrap/update-project.ps1') -Package $package -Approve
    if ($LASTEXITCODE -ne 0) { throw 'Real update failed' }
    $updated=Join-Path $hostRoot 'web/release-smoke.txt'
    if (-not (Test-Path -LiteralPath $updated)) { throw 'New file missing after update' }
    $new=Get-Content -LiteralPath $session -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($new.pid -eq $state.pid -or $new.app -ne 'Tenmiyora') { throw 'Expected a fresh Tenmiyora process' }
    $health=Invoke-RestMethod -Uri ($new.url+'/health') -TimeoutSec 2 -Headers @{'X-Tenmiyora-Token'=[string]$new.token}
    if ($health.pid -ne $new.pid) { throw 'Updated process failed health' }
    Write-Host 'Real Windows update, restart and authenticated health passed.'
    Invoke-RestMethod -Method Post -Uri ($new.url+'/shutdown') -TimeoutSec 3 -Headers @{'X-Tenmiyora-Token'=[string]$new.token} | Out-Null
} finally {
    if ($old) { try { & taskkill.exe /PID $old.Id /T /F 2>$null | Out-Null } catch {} }
    if (Test-Path -LiteralPath $session) {
        try {
            $state=Get-Content -LiteralPath $session -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.url -match '^http://127\.0\.0\.1:[0-9]+$') {
                Invoke-RestMethod -Method Post -Uri ($state.url+'/shutdown') -TimeoutSec 2 -Headers @{'X-Tenmiyora-Token'=[string]$state.token} | Out-Null
            }
        } catch {}
    }
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $base -Force -Recurse -ErrorAction SilentlyContinue
}
