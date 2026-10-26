$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtime = Join-Path $root '.runtime'
$statePath = Join-Path $runtime 'session.json'
$script:child = $null
$script:childStarted = $false
$script:tray = $null
$script:session = $null
$script:stop = $false
$script:consoleHidden = $false
$script:logPath = $null
$lock = $null
$exitCode = 0
$script:pendingUpdate = $null
$script:restoreUpdate = $false

function Write-Status([string]$Message) {
    Write-Host $Message
    if ($script:logPath) {
        [IO.File]::AppendAllText($script:logPath, "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message`r`n", $utf8)
    }
}

function Get-Session {
    if (Test-Path -LiteralPath $statePath) {
        try { return ([IO.File]::ReadAllText($statePath, $utf8) | ConvertFrom-Json) } catch { return $null }
    }
    return $null
}

function Test-Session($Session) {
    if (-not $Session -or $Session.app -ne 'Tenmiyora') { return $false }
    if ($Session.url -notmatch '^http://127\.0\.0\.1:[0-9]{1,5}$') { return $false }
    if ([string]::IsNullOrWhiteSpace($Session.token)) { return $false }
    try {
        $reply = Invoke-RestMethod -Uri ($Session.url + '/health') -TimeoutSec 2 -UseBasicParsing -Headers @{'X-Tenmiyora-Token' = $Session.token}
        return ($reply.app -eq 'Tenmiyora' -and $reply.pid -eq $Session.pid)
    } catch { return $false }
}

function Open-Site {
    try { Start-Process -FilePath $script:session.url | Out-Null }
    catch { Write-Status "⚠ Не удалось открыть браузер. Откройте вручную: $($script:session.url)" }
}

function Show-Console {
    if ('Tenmiyora.Native' -as [type]) {
        $handle = [Tenmiyora.Native]::GetConsoleWindow()
        if ($handle -ne [IntPtr]::Zero) { [void][Tenmiyora.Native]::ShowWindow($handle, 5) }
    }
    $script:consoleHidden = $false
}

function Hide-Console {
    if ($script:tray -and $script:tray.Visible) {
        $handle = [Tenmiyora.Native]::GetConsoleWindow()
        if ($handle -ne [IntPtr]::Zero) {
            [void][Tenmiyora.Native]::ShowWindow($handle, 0)
            $script:consoleHidden = $true
        }
    }
}

function Stop-Server {
    if ($script:childStarted -and -not $script:child.HasExited) {
        if ($script:session -and $script:session.pid -eq $script:child.Id) {
            try { Invoke-RestMethod -Method Post -Uri ($script:session.url + '/shutdown') -TimeoutSec 2 -UseBasicParsing -Headers @{'X-Tenmiyora-Token'=$script:session.token} | Out-Null } catch { }
        }
        if (-not $script:child.WaitForExit(3000)) { $script:child.Kill(); [void]$script:child.WaitForExit(3000) }
    }
}

function Run-UpdateWorker([string]$Job, [string]$Action, [string]$ExpectedHash) {
    if ($Job -notmatch '^[0-9a-f]{32}$') { throw 'Неверный номер обновления.' }
    $worker = Join-Path $runtime ('updates\staging\' + $Job + '\worker.py')
    if (-not (Test-Path -LiteralPath $worker) -or (Get-ArchiveSha256 $worker) -ne $ExpectedHash) { throw 'Установщик обновления повреждён. Резервные копии сохранены в .runtime\updates.' }
    $workerInfo = New-Object System.Diagnostics.ProcessStartInfo
    $workerInfo.FileName = $python
    $workerInfo.Arguments = '-I -X utf8 "' + $worker + '" --root "' + $root + '" --job ' + $Job + ' --action ' + $Action
    $workerInfo.WorkingDirectory = $root
    $workerInfo.UseShellExecute = $false
    $workerInfo.CreateNoWindow = $true
    $workerInfo.RedirectStandardOutput = $true
    $workerInfo.RedirectStandardError = $true
    $workerProcess = New-Object System.Diagnostics.Process
    $workerProcess.StartInfo = $workerInfo
    try {
        [void]$workerProcess.Start()
        $workerOut = $workerProcess.StandardOutput.ReadToEndAsync()
        $workerError = $workerProcess.StandardError.ReadToEndAsync()
        while (-not $workerProcess.WaitForExit(100)) {
            if ($script:tray) { [System.Windows.Forms.Application]::DoEvents() }
        }
        if ($workerOut.Result.Trim()) { Write-Status $workerOut.Result.Trim() }
        if ($workerError.Result.Trim()) { Write-Status $workerError.Result.Trim() }
        return $workerProcess.ExitCode
    } finally { $workerProcess.Dispose() }
}

function Find-Python([bool]$PortableOnly) {
    $candidates = New-Object System.Collections.ArrayList
    $localPaths = @('.runtime\python\python.exe')
    if (-not $PortableOnly) { $localPaths += '.venv\Scripts\python.exe' }
    foreach ($relative in $localPaths) {
        $path = Join-Path $root $relative
        if (Test-Path -LiteralPath $path) { [void]$candidates.Add(@{Path=$path; Prefix=''}) }
    }
    if (-not $PortableOnly) {
        foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
            $commands = @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)
            foreach ($command in $commands) {
                if ($command.Source -like '*\Microsoft\WindowsApps\*') { continue }
                $prefix = ''
                if ($name -eq 'py.exe') { $prefix = '-3 ' }
                [void]$candidates.Add(@{Path=$command.Source; Prefix=$prefix})
            }
        }
        # Python may be installed without being added to PATH.
        foreach ($key in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
            if (-not (Test-Path -LiteralPath $key)) { continue }
            foreach ($versionKey in @(Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue)) {
                $installKey = Join-Path $versionKey.PSPath 'InstallPath'
                if (-not (Test-Path -LiteralPath $installKey)) { continue }
                $properties = Get-ItemProperty -LiteralPath $installKey -ErrorAction SilentlyContinue
                $path = $properties.ExecutablePath
                if (-not $path -and $properties.'(default)') { $path = Join-Path $properties.'(default)' 'python.exe' }
                if ($path -and (Test-Path -LiteralPath $path)) { [void]$candidates.Add(@{Path=$path; Prefix=''}) }
            }
        }
    }
    $probe = Join-Path $PSScriptRoot 'probe.py'
    foreach ($candidate in $candidates) {
        $detected = Test-PythonCandidate -Path $candidate.Path -Prefix $candidate.Prefix -ProbePath $probe
        if ($detected) {
            Write-Status "✓ Python $($detected.version): $($detected.executable)"
            return [string]$detected.executable
        }
        Write-Status "⚠ Не подходит Python: $($candidate.Path)"
    }
    return $null
}

try {
    $options = @($env:TENMIYORA_MODE, $env:TENMIYORA_OPTION, $env:TENMIYORA_EXTRA) | Where-Object { $_ }
    foreach ($option in $options) {
        if ($option -notin @('--console', '--no-browser', '--portable')) {
            throw 'Доступные параметры: --console (оставить консоль), --no-browser (не открывать браузер), --portable (использовать только переносной Python).'
        }
    }
    . (Join-Path $PSScriptRoot 'python-runtime.ps1')
    [void][IO.Directory]::CreateDirectory($runtime)
    try {
        $lock = [IO.File]::Open((Join-Path $runtime 'launcher.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        # Another launcher can still be starting. Never trust a stale URL alone.
        $deadline = [DateTime]::UtcNow.AddSeconds(240)
        Write-Status '◈ Другая копия подготавливает Tenmiyora. Ожидание запуска…'
        while ([DateTime]::UtcNow -lt $deadline) {
            $script:session = Get-Session
            if (Test-Session $script:session) {
                Write-Status '✓ Tenmiyora уже работает.'
                if ($options -notcontains '--no-browser') { Open-Site }
                exit 0
            }
            Start-Sleep -Milliseconds 250
        }
        throw 'Другая копия ещё запускается или папка недоступна для записи. Проверьте консоль первого запуска и права на папку.'
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $script:logPath = Join-Path $runtime "launch-$stamp.log"
    Write-Status '✦ Tenmiyora · v0.5.0 · Подготовка'
    # Recover an orphaned instance only after an authenticated health check.
    $previous = Get-Session
    if (Test-Session $previous) {
        try {
            Invoke-RestMethod -Method Post -Uri ($previous.url + '/shutdown') -TimeoutSec 3 -UseBasicParsing -Headers @{'X-Tenmiyora-Token'=$previous.token} | Out-Null
        } catch { throw 'Не удалось завершить предыдущий сервер. Повторите запуск через несколько секунд.' }
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Write-Status '◈ Проверка Python и стандартных модулей'
    $python = Find-Python -PortableOnly ($options -contains '--portable')
    if (-not $python) {
        Write-Status '⚙ Рабочий Python не найден. Подготовка локальной среды без установки в Windows'
        $python = Install-PortablePython -RuntimeDirectory $runtime -ProbePath (Join-Path $PSScriptRoot 'probe.py') -ManifestPath (Join-Path $PSScriptRoot 'python-runtime.json')
    }
    $transactionPath = Join-Path $runtime 'updates\transaction.json'
    if (Test-Path -LiteralPath $transactionPath) {
        $script:pendingUpdate = [IO.File]::ReadAllText($transactionPath, $utf8) | ConvertFrom-Json
        if ($script:pendingUpdate.phase -eq 'applying') {
            Write-Status '↻ Восстановление прерванного обновления'
            if ((Run-UpdateWorker $script:pendingUpdate.job 'recover' $script:pendingUpdate.worker_sha) -ne 0) { throw 'Автоматическое восстановление не завершено. Сохраните папку .runtime\updates и журнал ошибки.' }
            $script:pendingUpdate = $null
            $exitCode=75
            exit 75
        }
        if ($script:pendingUpdate.phase -ne 'awaiting_health') { throw 'Неизвестное состояние установки обновления.' }
    }
    $restartPath = Join-Path $runtime 'updates\restart.json'
    $restartData = $null
    if (Test-Path -LiteralPath $restartPath) { $restartData = [IO.File]::ReadAllText($restartPath, $utf8) | ConvertFrom-Json }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $python
    $info.Arguments = '-I -X utf8 "' + (Join-Path $PSScriptRoot 'server.py') + '"'
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['TENMIYORA_MANAGED'] = '1'
    if ($restartData -and $restartData.port -ge 1 -and $restartData.port -le 65535) { $info.EnvironmentVariables['TENMIYORA_PORT'] = [string]$restartData.port }
    $info.EnvironmentVariables['TENMIYORA_STATE'] = $statePath
    $info.EnvironmentVariables['TENMIYORA_PARENT_PID'] = [string]$PID
    $info.EnvironmentVariables['TENMIYORA_SERVER_LOG'] = (Join-Path $runtime "server-$stamp.log")
    $script:child = New-Object System.Diagnostics.Process
    $script:child.StartInfo = $info
    [void]$script:child.Start()
    $script:childStarted = $true
    $stdout = $script:child.StandardOutput.ReadToEndAsync()
    $stderr = $script:child.StandardError.ReadToEndAsync()
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($script:child.HasExited) { throw "Сервер завершился при запуске: $($stderr.Result)" }
        $script:session = Get-Session
        if ($script:session -and $script:session.pid -eq $script:child.Id -and (Test-Session $script:session)) { $ready=$true; break }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) { throw 'Сервер не ответил за 20 секунд. Подробности находятся в .runtime.' }
    if ($script:pendingUpdate) {
        $planVersion = $script:pendingUpdate.version
        if ($script:session.version -ne $planVersion) { throw 'Запущена неожиданная версия после обновления.' }
        if ((Run-UpdateWorker $script:pendingUpdate.job 'finish' $script:pendingUpdate.worker_sha) -ne 0) { throw 'Новая версия не прошла окончательную проверку файлов.' }
        $script:pendingUpdate = $null
    }
    Remove-Item -LiteralPath $restartPath -Force -ErrorAction SilentlyContinue
    Write-Status "✓ Готово: $($script:session.url)"
    Write-Status "Журналы: $runtime"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Tenmiyora {
    public static class Native {
        [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
}
'@
        $menu = New-Object System.Windows.Forms.ContextMenuStrip
        $open = $menu.Items.Add('Открыть Tenmiyora')
        $open.add_Click({ Open-Site })
        $show = $menu.Items.Add('Показать консоль')
        $show.add_Click({ Show-Console })
        $hide = $menu.Items.Add('Свернуть в трей')
        $hide.add_Click({ Hide-Console })
        $logs = $menu.Items.Add('Открыть журналы')
        $logs.add_Click({
            try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $runtime + '"') | Out-Null }
            catch { Show-Console; Write-Host '⚠ Не удалось открыть папку журналов.' }
        })
        [void]$menu.Items.Add('-')
        $quit = $menu.Items.Add('Выход')
        $quit.add_Click({ $script:stop=$true })
        $script:tray = New-Object System.Windows.Forms.NotifyIcon
        $script:tray.Icon = [System.Drawing.SystemIcons]::Application
        $script:tray.Text = 'Tenmiyora · работает'
        $script:tray.ContextMenuStrip = $menu
        $script:tray.add_DoubleClick({ Open-Site })
        $script:tray.Visible = $true
        [System.Windows.Forms.Application]::DoEvents()
    } catch {
        if ($script:tray) { $script:tray.Dispose(); $script:tray=$null }
        Write-Status '⚠ Трей недоступен. Оставьте консоль открытой; Ctrl+C завершает работу.'
    }
    if ($options -notcontains '--no-browser' -and (-not $restartData -or $restartData.url -ne $script:session.url)) { Open-Site }
    if ($options -notcontains '--console') { Hide-Console }
    while (-not $script:stop) {
        $requestPath = Join-Path $runtime 'updates\request.json'
        if (Test-Path -LiteralPath $requestPath) {
            $updateRequest = [IO.File]::ReadAllText($requestPath, $utf8) | ConvertFrom-Json
            Remove-Item -LiteralPath $requestPath -Force
            if ($updateRequest.token -eq $script:session.token -and $updateRequest.job -match '^[0-9a-f]{32}$') {
                $workerPath = Join-Path $runtime ('updates\staging\' + $updateRequest.job + '\worker.py')
                if ((Get-ArchiveSha256 $workerPath) -ne $updateRequest.worker_sha) { throw 'Проверка установщика обновления не пройдена.' }
                $port = ([Uri]$script:session.url).Port
                @{port=$port; url=$script:session.url} | ConvertTo-Json | Set-Content -LiteralPath $restartPath -Encoding UTF8
                Write-Status '↻ Установка обновления и перезапуск Tenmiyora'
                Stop-Server
                $workerCode = Run-UpdateWorker $updateRequest.job 'apply' $updateRequest.worker_sha
                if ($workerCode -ne 0 -and (Test-Path -LiteralPath $transactionPath)) { throw 'Установка не завершена; требуется восстановление из резервной копии.' }
                $exitCode=75
                $script:stop=$true
                break
            }
        }
        if ($script:child.HasExited) { throw "Сервер неожиданно завершился (код $($script:child.ExitCode)): $($stderr.Result)" }
        if ($script:tray) { [System.Windows.Forms.Application]::DoEvents() }
        Start-Sleep -Milliseconds 150
    }
} catch {
    Show-Console
    $exitCode=1
    if ($script:pendingUpdate) { $script:restoreUpdate=$true }
    try { Write-Status "✕ $($_.Exception.Message)" } catch { Write-Host "✕ $($_.Exception.Message)" }
} finally {
    Stop-Server
    if ($script:restoreUpdate) {
        try {
            if ((Run-UpdateWorker $script:pendingUpdate.job 'rollback' $script:pendingUpdate.worker_sha) -eq 0) { $exitCode=75 }
        } catch { Show-Console; Write-Host "✕ Восстановление не завершено: $($_.Exception.Message)" }
    }
    if ($script:tray) { $script:tray.Visible=$false; $script:tray.Dispose() }
    if ($script:child) { $script:child.Dispose() }
    if ($lock) { $lock.Dispose() }
    if ($exitCode -ne 0 -and $exitCode -ne 75) { Show-Console }
}
exit $exitCode
