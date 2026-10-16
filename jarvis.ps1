# Convenience launcher for this checkout. The interpreter path can be overridden.
$jarvisPython = $env:JARVIS_PYTHON
if (-not $jarvisPython) {
    $jarvisPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'JarvisData\envs\dev\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $jarvisPython -PathType Leaf)) {
    Write-Error 'Set JARVIS_PYTHON to the prepared Python interpreter; see docs/core-bootstrap.md.'
    exit 2
}
& $jarvisPython (Join-Path $PSScriptRoot 'apps\cli\main.py') @args
exit $LASTEXITCODE
