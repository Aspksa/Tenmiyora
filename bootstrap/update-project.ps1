# Windows project updater. Run from separate PowerShell process, not the server.
# Syntax: powershell -NoProfile -File bootstrap/update-project.ps1 -Package C:\path\staged -Approve
param([Parameter(Mandatory=$true)][string]$Package,[switch]$Approve)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtime=Join-Path $root '.runtime'
$sessionFile=Join-Path $runtime 'session.json'
$packageFull=[IO.Path]::GetFullPath($Package)
$lock=$null
$backup=$null
$changed=New-Object 'System.Collections.Generic.List[string]'
$created=New-Object 'System.Collections.Generic.List[string]'
$launcher=$null
$installed=$false

function Get-Session {
    if (-not (Test-Path -LiteralPath $sessionFile)) { return $null }
    try { return (Get-Content -LiteralPath $sessionFile -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}
function Test-Health($s) {
    if (-not $s -or $s.app -ne 'Tenmiyora' -or $s.url -notmatch '^http://127\.0\.0\.1:[0-9]{1,5}$' -or -not $s.token) { return $false }
    try {
        $reply=Invoke-RestMethod -Uri ($s.url+'/health') -Headers @{'X-Tenmiyora-Token'=[string]$s.token} -TimeoutSec 2
        return ($reply.app -eq 'Tenmiyora' -and $reply.pid -eq $s.pid)
    } catch { return $false }
}
function New-Launcher {
    $bat=Join-Path $root 'Tenmiyora.bat'
    return (Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c',('"'+$bat+'" --no-browser')) -PassThru -WindowStyle Hidden)
}
function Wait-Health($previousPid) {
    for ($i=0;$i -lt 100;$i++) {
        $s=Get-Session
        if ($s -and $s.pid -ne $previousPid -and (Test-Health $s)) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return $false
}
try {
    if (-not $Approve) { throw 'Explicit -Approve is required.' }
    if (-not (Test-Path -LiteralPath $packageFull -PathType Container)) { throw 'Staged package not found.' }
    if ($packageFull -eq $root -or $packageFull.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Package must be outside the project.' }
    $python=Join-Path $runtime 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $cmd=Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
        $python=$cmd.Source
    }
    # Verify the original signed-by-content manifest before touching the server.
    & $python -I -X utf8 (Join-Path $PSScriptRoot 'release_operator.py') verify --package $packageFull
    if ($LASTEXITCODE -ne 0) { throw 'Update manifest rejected.' }
    $manifest=Get-Content -LiteralPath (Join-Path $packageFull 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $manifest.files -or $manifest.files.Count -gt 1000) { throw 'Empty or oversized package.' }
    foreach ($entry in $manifest.files) {
        $rel=[string]$entry.path
        if ($rel -notmatch '^(bootstrap/[^/]+|web/.+|Tenmiyora\.bat)$' -or $rel -match '(^|/)\.' -or $rel -match '(^|/)\.runtime(/|$)' -or $rel.Contains('..')) {
            throw 'Package contains a forbidden path.'
        }
    }
    $current=Get-Session
    $previousPid=0
    if ($current) {
        if (-not (Test-Health $current)) { throw 'Existing session cannot be authenticated. Exit the app manually.' }
        $previousPid=$current.pid
        Invoke-RestMethod -Method Post -Uri ($current.url+'/shutdown') -TimeoutSec 3 -Headers @{'X-Tenmiyora-Token'=[string]$current.token} | Out-Null
    }
    [IO.Directory]::CreateDirectory($runtime) | Out-Null
    $locked=$false
    for ($i=0;$i -lt 100;$i++) {
        try {
            $lock=[IO.File]::Open((Join-Path $runtime 'launcher.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
            $locked=$true
            break
        } catch [IO.IOException] { Start-Sleep -Milliseconds 200 }
    }
    if (-not $locked) { throw 'Launcher did not release the lock.' }
    # Only an unchanged, stopped project can be replaced.
    if (Test-Health (Get-Session)) { throw 'Server is still running.' }
    $backup=Join-Path $env:TEMP ('tenmiyora-update-backup-'+[guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    foreach ($entry in $manifest.files) {
        $rel=([string]$entry.path).Replace('/',[IO.Path]::DirectorySeparatorChar)
        $src=Join-Path $packageFull $rel
        $dst=Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw 'Missing package file.' }
        # Prevent substituting a junction/symlink into project directories.
        $parent=Split-Path -Parent $dst
        $walk=$parent
        while ($walk -and $walk.Length -ge $root.Length) {
            if (Test-Path -LiteralPath $walk) {
                if ((Get-Item -LiteralPath $walk -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked project directory refused.' }
            }
            if ($walk -eq $root) { break }
            $walk=Split-Path -Parent $walk
        }
        if (Test-Path -LiteralPath $dst) {
            if ((Get-Item -LiteralPath $dst -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked file refused.' }
            $save=Join-Path $backup $rel
            [IO.Directory]::CreateDirectory((Split-Path -Parent $save)) | Out-Null
            Copy-Item -LiteralPath $dst -Destination $save -Force
            $changed.Add($rel)
        } else { $created.Add($rel) }
        [IO.Directory]::CreateDirectory($parent) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
        $hash=(Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne [string]$entry.sha256) { throw 'Installed file hash mismatch.' }
    }
    $installed=$true
    $lock.Dispose();$lock=$null
    $launcher=New-Launcher
    if (-not (Wait-Health $previousPid)) { throw 'New server failed health verification.' }
    Write-Host 'Tenmiyora update installed, restarted and authenticated health passed.'
} catch {
    $errorText=$_.Exception.Message
    if ($lock) { $lock.Dispose();$lock=$null }
    if ($backup) {
        $active=Get-Session
        if ($active -and (Test-Health $active)) {
            try { Invoke-RestMethod -Method Post -Uri ($active.url+'/shutdown') -TimeoutSec 3 -Headers @{'X-Tenmiyora-Token'=[string]$active.token} | Out-Null } catch {}
        }
        $locked=$false
        for ($i=0;$i -lt 100;$i++) {
            try { $lock=[IO.File]::Open((Join-Path $runtime 'launcher.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$locked=$true;break }
            catch [IO.IOException] { Start-Sleep -Milliseconds 200 }
        }
        if ($locked -and -not (Test-Health (Get-Session))) {
            foreach ($rel in $created) { $p=Join-Path $root $rel;if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force } }
            foreach ($rel in $changed) { Copy-Item -LiteralPath (Join-Path $backup $rel) -Destination (Join-Path $root $rel) -Force }
            $lock.Dispose();$lock=$null
            $launcher=New-Launcher
            Write-Host 'Previous files restored; previous launcher started.'
        } else { Write-Warning 'Recovery blocked by a running launcher; preserve backup for manual restoration.' }
    }
    throw $errorText
} finally {
    if ($lock) { $lock.Dispose() }
    if ($installed -and $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
}
