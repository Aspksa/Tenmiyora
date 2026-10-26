$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\bootstrap\python-runtime.ps1')
function Write-Status([string]$Message) { Write-Host $Message }
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-Failure([scriptblock]$Action, [string]$Expected) {
    $failure = $null
    try { & $Action } catch { $failure = $_.Exception.Message }
    Assert-True ($failure -and $failure.Contains($Expected)) "Expected error containing '$Expected', received '$failure'"
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('Tenmiyora тест ! ' + [Guid]::NewGuid().ToString('N'))
$savedArchitecture = $env:PROCESSOR_ARCHITECTURE
$savedWowArchitecture = $env:PROCESSOR_ARCHITEW6432
try {
    foreach ($item in @(@('AMD64', 'amd64'), @('x86', 'win32'), @('ARM64', 'arm64'))) {
        $env:PROCESSOR_ARCHITEW6432 = $null
        $env:PROCESSOR_ARCHITECTURE = $item[0]
        Assert-True ((Get-PythonArchitecture) -eq $item[1]) 'Wrong native architecture'
    }
    $env:PROCESSOR_ARCHITECTURE = 'x86'
    $env:PROCESSOR_ARCHITEW6432 = 'AMD64'
    Assert-True ((Get-PythonArchitecture) -eq 'amd64') 'WOW64 architecture was ignored'
    $env:PROCESSOR_ARCHITECTURE = 'AMD64'
    $env:PROCESSOR_ARCHITEW6432 = $null
    [void][IO.Directory]::CreateDirectory($temporary)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $fixture = Join-Path $temporary 'fixture'
    [void][IO.Directory]::CreateDirectory($fixture)
    [IO.File]::WriteAllText((Join-Path $fixture 'python.exe'), 'fixture: never executed')
    $script:fixtureArchive = Join-Path $temporary 'fixture.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($fixture, $script:fixtureArchive)
    $runtime = Join-Path $temporary 'runtime'
    $previous = Join-Path $runtime 'python'
    [void][IO.Directory]::CreateDirectory($previous)
    $marker = Join-Path $previous 'previous.txt'
    [IO.File]::WriteAllText($marker, 'keep previous runtime')
    $manifestPath = Join-Path $temporary 'manifest.json'
    $manifest = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '..\bootstrap\python-runtime.json')) | ConvertFrom-Json
    $script:version = $manifest.version
    $goodHash = (Get-FileHash -LiteralPath $script:fixtureArchive -Algorithm SHA256).Hash
    $manifest.packages.amd64.sha256 = $goodHash
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    # Controlled fixtures test failures without executing untrusted files or using the network.
    function Save-PythonArchive([string]$Url, [string]$Destination) {
        if ($script:networkFailure) { throw 'offline fixture' }
        [IO.File]::Copy($script:fixtureArchive, $Destination)
    }
    function Test-PythonCandidate([string]$Path, [string]$Prefix, [string]$ProbePath) {
        if ($script:probeFailure -eq 'staged' -or ($script:probeFailure -eq 'installed' -and (Split-Path -Leaf (Split-Path -Parent $Path)) -eq 'python')) { return $null }
        return [PSCustomObject]@{executable=$Path; version=$script:version}
    }
    $script:networkFailure = $true
    Assert-Failure { Install-PortablePython $runtime 'unused' $manifestPath } 'offline fixture'
    Assert-True (Test-Path -LiteralPath $marker) 'Offline failure changed previous runtime'
    $script:networkFailure = $false

    $manifest.packages.amd64.sha256 = '0' * 64
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Assert-Failure { Install-PortablePython $runtime 'unused' $manifestPath } 'SHA-256'
    Assert-True (Test-Path -LiteralPath $marker) 'Hash failure changed previous runtime'
    $manifest.packages.amd64.sha256 = $goodHash
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $script:probeFailure = 'staged'
    Assert-Failure { Install-PortablePython $runtime 'unused' $manifestPath } 'стандартных модулей'
    Assert-True (Test-Path -LiteralPath $marker) 'Failed staged probe changed previous runtime'
    $script:probeFailure = 'installed'
    Assert-Failure { Install-PortablePython $runtime 'unused' $manifestPath } 'после переноса'
    Assert-True (Test-Path -LiteralPath $marker) 'Failed installed probe did not restore previous runtime'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $previous 'python.exe'))) 'Failed runtime was left installed'

    $script:probeFailure = ''
    $result = Install-PortablePython $runtime 'unused' $manifestPath
    Assert-True (Test-Path -LiteralPath $result) 'Successful install is missing'
    Assert-True (-not (Test-Path -LiteralPath $marker)) 'Old runtime was not replaced'
    Assert-True (@(Get-ChildItem -LiteralPath $runtime -Filter 'python-setup-*').Count -eq 0) 'Staging directories were left behind'
    Write-Host 'Architecture, network failure, SHA-256 rejection, probe failures, rollback and installation: OK'
} finally {
    $env:PROCESSOR_ARCHITECTURE = $savedArchitecture
    $env:PROCESSOR_ARCHITEW6432 = $savedWowArchitecture
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
