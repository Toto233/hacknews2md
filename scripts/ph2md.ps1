[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = $env:PUBLISHER_PYTHON
if (-not $python) {
    $localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython) {
        $python = $localPython
    }
}
if (-not $python) {
    $python = $env:HACKNEWS_PYTHON
}
if (-not $python) {
    $defaultPython311 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-Path -LiteralPath $defaultPython311) {
        $python = $defaultPython311
    }
}
if (-not $python) {
    $python = "python"
}

& $python -m ph2md.cli @Arguments
exit $LASTEXITCODE
