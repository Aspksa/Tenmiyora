$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$code = 1
try {
    do {
        & $powershell -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $root 'bootstrap\launch.ps1')
        $code = $LASTEXITCODE
        if ($code -eq 75) { $env:TENMIYORA_RESTART = '1' }
    } while ($code -eq 75)
} catch { Write-Host "Ошибка запуска Tenmiyora: $($_.Exception.Message)"; $code = 1 }
if ($code -ne 0) { [void](Read-Host 'Нажмите Enter, чтобы закрыть окно') }
exit $code
