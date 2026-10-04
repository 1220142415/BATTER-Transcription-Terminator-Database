param([switch]$Refresh, [switch]$Force, [switch]$RestartGateway)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$area = Join-Path $root 'dist/v05-hf-preview'
$pointer = Join-Path $area 'current.json'
$record = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
$python = 'C:/Python314/python.exe'
$node = 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$startup = New-CimInstance -CimClass (Get-CimClass Win32_ProcessStartup) -ClientOnly -Property @{ShowWindow=[uint16]0}

function Test-Listening([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
function Start-Detached([string]$Command) {
    # WMI owns these hidden processes so closing a tool's shell does not close the preview.
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine=$Command; CurrentDirectory=$root; ProcessStartupInformation=$startup
    }
    if ($created.ReturnValue -ne 0) { throw "Background launch failed: $($created.ReturnValue)" }
    [int]$created.ProcessId
}
function Wait-Listening([int]$Port) {
    for ($attempt=0; $attempt -lt 45; $attempt++) {
        if (Test-Listening $Port) { return }
        Start-Sleep -Seconds 1
    }
    throw "Preview port $Port did not start"
}

if ($RestartGateway -and (Test-Listening 17998)) {
    $owner = Get-NetTCPConnection -LocalPort 17998 -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
    if ($process.CommandLine -notmatch 'bted_hf_gateway\.py' -or $process.CommandLine -notmatch '--ssh-bridge') { throw 'Gateway port belongs to an unrelated process' }
    Stop-Process -Id $owner
    for ($attempt=0; $attempt -lt 20 -and (Test-Listening 17998); $attempt++) { Start-Sleep -Milliseconds 250 }
}
if (-not (Test-Listening 17998)) {
    $gatewayLog = Join-Path $area 'gateway.background.log'
    $command = 'cmd.exe /d /c ""{0}" -u "{1}" --snapshots "{2}" --port 17998 --ssh-bridge >> "{3}" 2>&1"' -f $python,(Join-Path $root 'scripts/bted_hf_gateway.py'),(Join-Path $area 'gateway-snapshots'),$gatewayLog
    $gatewayPid = Start-Detached $command
    Wait-Listening 17998
    Write-Output "Gateway started: $gatewayPid"
}
$backendPort = ([uri]$record.backend).Port
if (-not (Test-Listening $backendPort)) {
    $candidate = (Resolve-Path -LiteralPath $record.candidate).Path
    $workerLog = Join-Path $candidate 'worker.background.log'
    $command = 'cmd.exe /d /c ""{0}" "{1}" dev --local --config "{2}" --persist-to "{3}" --ip 127.0.0.1 --port {4} --inspector-port 0 >> "{5}" 2>&1"' -f $node,(Join-Path $root 'dist/wrangler/node_modules/wrangler/bin/wrangler.js'),(Join-Path $candidate 'wrangler.json'),(Join-Path $candidate 'state'),$backendPort,$workerLog
    $workerShell = Start-Detached $command
    Wait-Listening $backendPort
    # stop_candidate expects the Node PID, whose arguments include --config.
    $worker = Get-CimInstance Win32_Process -Filter "ParentProcessId=$workerShell" | Where-Object { $_.Name -eq 'node.exe' }
    if (-not $worker) { throw 'Unable to identify the recovered Worker' }
    Set-Content -LiteralPath (Join-Path $candidate 'worker.pid') -Value $worker.ProcessId -Encoding ascii -NoNewline
    Write-Output "Worker recovered: $($worker.ProcessId)"
}
$expected = Get-Content -LiteralPath (Join-Path $record.candidate 'site/assets/data-release.json') -Raw | ConvertFrom-Json
$health = Invoke-RestMethod -Uri "$($record.backend)/api/health" -TimeoutSec 10
if ($health.release.canonical_manifest_sha256 -ne $expected.releaseManifestSha256) { throw 'Recovered Worker release mismatch' }
if (-not (Test-Listening 8797)) {
    $serveLog = Join-Path $area 'serve.background.log'
    $command = 'cmd.exe /d /c ""{0}" -u "{1}" serve --pointer "{2}" --port 8797 >> "{3}" 2>&1"' -f $python,(Join-Path $root 'scripts/serve_bted_hf_preview.py'),$pointer,$serveLog
    $servePid = Start-Detached $command
    Wait-Listening 8797
    Write-Output "Preview started: $servePid"
}
if ($Refresh) {
    $active = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'serve_bted_hf_preview\.py"? refresh' }
    if ($active) { throw 'A preview refresh is already running' }
    $refreshLog = Join-Path $area ('refresh.background.' + (Get-Date -Format yyyyMMdd-HHmmss) + '.log')
    $command = 'cmd.exe /d /c ""{0}" -u "{1}" refresh --pointer "{2}" --gateway http://127.0.0.1:17998/ > "{3}" 2>&1"' -f $python,(Join-Path $root 'scripts/serve_bted_hf_preview.py'),$pointer,$refreshLog
    if ($Force) { $command = $command.Replace(' --gateway', ' --force --gateway') }
    $refreshPid = Start-Detached $command
    Write-Output "Refresh started: $refreshPid; log: $refreshLog"
}
