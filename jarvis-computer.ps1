$jarvisComputerPython = $env:JARVIS_PYTHON
if (-not $jarvisComputerPython) {
    $jarvisComputerPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'JarvisData\envs\dev\Scripts\python.exe'
}
& $jarvisComputerPython (Join-Path $PSScriptRoot 'apps\computer-use\main.py') @args
exit $LASTEXITCODE
