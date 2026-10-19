param([switch]$CheckOnly)
# Run locally after manually disconnecting network links. Never changes adapters.
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$JarvisRoot = Split-Path -Parent $PSScriptRoot
$JarvisPython = 'H:\JarvisData\envs\dev\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $JarvisPython -PathType Leaf)) { throw 'Python runtime missing' }
function Read-NetworkState {
    $physical = @(Get-NetAdapter -Physical | Select-Object Name,Status)
    $routes = @(Get-NetRoute | Where-Object { $_.DestinationPrefix -in @('0.0.0.0/0','::/0') -and $_.State -eq 'Alive' } | Select-Object InterfaceIndex,DestinationPrefix)
    [pscustomobject]@{ physical=$physical; defaultRoutes=$routes; noUpPhysical=(@($physical | Where-Object Status -eq 'Up').Count -eq 0); noDefaultRoute=($routes.Count -eq 0) }
}
$before = Read-NetworkState
$modelPortBusy = @(Get-NetTCPConnection -LocalPort 18180 -State Listen -ErrorAction SilentlyContinue).Count -gt 0
if ($CheckOnly) { [pscustomobject]@{ network=$before; modelPortBusy=$modelPortBusy; ready=($before.noUpPhysical -and $before.noDefaultRoute -and -not $modelPortBusy) } | ConvertTo-Json -Depth 7; exit 0 }
if ($modelPortBusy) { throw 'Stop the local model in Jarvis settings before this cold-start test. The probe will not take over an existing service.' }
if (-not $before.noUpPhysical -or -not $before.noDefaultRoute) {
    throw 'Disconnect Wi-Fi/Ethernet/VPN manually first. No adapters or running Jarvis instance were changed.'
}
$resultRoot = Join-Path 'H:\JarvisData\diagnostics' ('k2-offline-device-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $resultRoot) { throw 'Use a fresh result path' }
New-Item -ItemType Directory -Path $resultRoot | Out-Null
$resultFile = Join-Path $resultRoot 'tasks.json'
$record = [ordered]@{ status='running'; started=(Get-Date).ToUniversalTime().ToString('o'); networkBefore=$before; adaptersChangedByProbe=$false; evidence=$resultFile }
try {
    Push-Location -LiteralPath $JarvisRoot
    try {
        & $JarvisPython tools/probe_offline_tasks.py --output $resultFile
        $probeExit = $LASTEXITCODE
    } finally { Pop-Location }
    $after = Read-NetworkState
    $record.networkAfter = $after
    $record.probeExit = $probeExit
    $record.status = if ($probeExit -eq 0 -and $after.noUpPhysical -and $after.noDefaultRoute) { 'awaiting_owner_interval_attestation' } else { 'failed' }
    $record.limits = 'Adapter and default-route snapshots at both ends, not continuous packet capture or an OS reboot. Owner must confirm links remained disconnected throughout. Local engine is cold-started; production data is not used.'
} catch {
    $record.status = 'failed'
    $record.error = $_.Exception.Message
    throw
} finally {
    $record.finished = (Get-Date).ToUniversalTime().ToString('o')
    $record | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $resultRoot 'network.json') -Encoding utf8
    Write-Host "Evidence: $resultRoot"
    Write-Host 'You may reconnect the network now. This script did not change any adapter.'
}
if ($record.status -eq 'failed') { exit 1 }
