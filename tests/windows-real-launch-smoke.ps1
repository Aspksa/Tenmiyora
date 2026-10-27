# Smoke-check the real BAT -> PowerShell -> Python server chain on Windows CI.
# Uses a temporary project copy and never touches user profiles or live installs.
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$source = Join-Path $repo 'Tenmiyora.bat'
if (-not (Test-Path -LiteralPath $source)) { throw 'Tenmiyora.bat is missing' }
$destination = Join-Path $env:TEMP ('tenmiyora-smoke-' + [guid]::NewGuid().ToString('N'))
$proc = $null
try {
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($item in @('Tenmiyora.bat','bootstrap','web')) {
        Copy-Item -LiteralPath (Join-Path $repo $item) -Destination $destination -Recurse -Force
    }
    $session = Join-Path $destination '.runtime\session.json'
    $bat = Join-Path $destination 'Tenmiyora.bat'
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', ('"' + $bat + '" --console --no-browser')) -PassThru -WindowStyle Hidden
    $ready = $false
    for ($i=0; $i -lt 180; $i++) {
        if (Test-Path -LiteralPath $session) {
            try {
                $data = Get-Content -LiteralPath $session -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($data.app -eq 'Tenmiyora' -and $data.url -match '^http://127\.0\.0\.1:[0-9]+$' -and $data.token) {
                    $headers = @{'X-Tenmiyora-Token'=[string]$data.token}
                    $health = Invoke-RestMethod -Uri ($data.url + '/health') -TimeoutSec 2 -Headers $headers
                    if ($health.app -eq 'Tenmiyora' -and $health.pid -eq $data.pid) {
                        $ready = $true
                        break
                    }
                }
            } catch { }
        }
        if ($proc.HasExited) { throw 'Launcher exited before server became healthy' }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Authenticated health never became ready' }
    Write-Host 'Authenticated real Windows launcher health: OK'
    Invoke-RestMethod -Method Post -Uri ($data.url + '/shutdown') -TimeoutSec 4 -Headers $headers | Out-Null
    Write-Host 'Authenticated shutdown: OK'
} finally {
    if ($proc) {
        try { & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null } catch { }
        $proc.Dispose()
    }
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination -Recurse -Force -ErrorAction SilentlyContinue
    }
}
