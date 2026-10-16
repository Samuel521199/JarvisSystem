# Independent deterministic maintenance entry. No business host or model imports.
$jarvisControlPython = $env:JARVIS_PYTHON
if (-not $jarvisControlPython) {
    $jarvisControlPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'JarvisData\envs\dev\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $jarvisControlPython -PathType Leaf)) {
    Write-Error 'Set JARVIS_PYTHON to the prepared Python interpreter.'
    exit 2
}
& $jarvisControlPython -B (Join-Path $PSScriptRoot 'runtime\recovery-cli\main.py') @args
exit $LASTEXITCODE
