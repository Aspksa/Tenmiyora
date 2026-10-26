# Functions only: importing this file does not download or install anything.
function Test-PythonCandidate([string]$Path, [string]$Prefix, [string]$ProbePath) {
    $process = $null
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Path
        $info.Arguments = $Prefix + '-I -X utf8 "' + $ProbePath + '"'
        $info.WorkingDirectory = Split-Path -Parent $ProbePath
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        [void]$process.Start()
        $outTask = $process.StandardOutput.ReadToEndAsync()
        $errTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(6000)) {
            $process.Kill()
            [void]$process.WaitForExit(2000)
            return $null
        }
        if ($process.ExitCode -eq 0) {
            $detected = $outTask.Result.Trim() | ConvertFrom-Json
            if (Test-Path -LiteralPath $detected.executable -PathType Leaf) { return $detected }
        }
    } catch { return $null }
    finally { if ($process) { $process.Dispose() } }
    return $null
}

function Get-PythonArchitecture {
    # PROCESSOR_ARCHITEW6432 describes the OS when launched from a 32-bit shell.
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    switch ($architecture.ToUpperInvariant()) {
        'AMD64' { return 'amd64' }
        'X86' { return 'win32' }
        'ARM64' { return 'arm64' }
        default { throw "Не поддерживается архитектура Windows: $architecture" }
    }
}

function Get-ArchiveSha256([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($Path)
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($stream) { $stream.Dispose() }
        $algorithm.Dispose()
    }
}

function Save-PythonArchive([string]$Url, [string]$Destination) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $oldProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        for ($attempt = 1; $attempt -le 2; $attempt++) {
            try {
                Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 60 -MaximumRedirection 0 -UserAgent 'Tenmiyora-Bootstrap/0.6.6' | Out-Null
                return
            } catch {
                Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
                if ($attempt -eq 2) { throw }
                Write-Status '⚠ Загрузка прервалась. Повторная попытка…'
                Start-Sleep -Seconds 1
            }
        }
    } finally { $ProgressPreference = $oldProgress }
}

function Install-PortablePython([string]$RuntimeDirectory, [string]$ProbePath, [string]$ManifestPath) {
    $manifest = [IO.File]::ReadAllText($ManifestPath) | ConvertFrom-Json
    $architecture = Get-PythonArchitecture
    $package = $manifest.packages.$architecture
    $expectedUrl = 'https://www.python.org/ftp/python/' + $manifest.version + '/python-' + $manifest.version + '-embed-' + $architecture + '.zip'
    if ($manifest.version -notmatch '^3\.[0-9]+\.[0-9]+$' -or -not $package -or $package.url -cne $expectedUrl -or $package.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'Некорректный манифест переносного Python. Скачайте целую актуальную версию Tenmiyora.'
    }
    [void][IO.Directory]::CreateDirectory($RuntimeDirectory)
    $stage = Join-Path $RuntimeDirectory ('python-setup-' + [Guid]::NewGuid().ToString('N'))
    $archive = Join-Path $stage 'python.zip'
    $unpacked = Join-Path $stage 'unpacked'
    $destination = Join-Path $RuntimeDirectory 'python'
    $backup = Join-Path $stage 'previous'
    [void][IO.Directory]::CreateDirectory($stage)
    $hadPrevious = $false
    $installed = $false
    $committed = $false
    try {
        Write-Status "↻ Загрузка официального Python $($manifest.version) ($architecture), около 12 МБ"
        Save-PythonArchive -Url $package.url -Destination $archive
        Write-Status '◈ Проверка SHA-256 архива'
        $actualHash = Get-ArchiveSha256 -Path $archive
        if ($actualHash -ine $package.sha256) { throw 'SHA-256 не совпал. Архив повреждён или подменён; установка отменена.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $unpacked)
        $candidate = Join-Path $unpacked 'python.exe'
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw 'В архиве отсутствует python.exe.' }
        Write-Status '◈ Пробный запуск переносного Python'
        $detected = Test-PythonCandidate -Path $candidate -Prefix '' -ProbePath $ProbePath
        if (-not $detected -or $detected.version -ne $manifest.version) { throw 'Переносной Python не прошёл проверку версии или стандартных модулей.' }
        if (Test-Path -LiteralPath $destination) {
            [IO.Directory]::Move($destination, $backup)
            $hadPrevious = $true
        }
        try {
            [IO.Directory]::Move($unpacked, $destination)
            $installed = $true
            $result = Test-PythonCandidate -Path (Join-Path $destination 'python.exe') -Prefix '' -ProbePath $ProbePath
            if (-not $result -or $result.version -ne $manifest.version) { throw 'Python не запустился после переноса в рабочую папку.' }
            $committed = $true
        } catch {
            if ($installed) { Remove-Item -LiteralPath $destination -Recurse -Force }
            if ($hadPrevious) { [IO.Directory]::Move($backup, $destination); $hadPrevious=$false }
            throw
        }
        Write-Status "✓ Переносной Python готов: $($result.executable)"
        return [string]$result.executable
    } catch {
        throw "Не удалось подготовить переносной Python: $($_.Exception.Message) Проверьте интернет и доступ к www.python.org, затем снова запустите Tenmiyora.bat. Для запуска без сети можно заранее распаковать официальный embedded Python в .runtime\python."
    } finally {
        # If restoring a previous runtime itself failed, preserve it for recovery.
        if ($committed -or -not $hadPrevious) {
            Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
