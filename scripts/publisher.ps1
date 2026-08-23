[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$publisher = Join-Path $projectRoot ".venv\Scripts\publisher.exe"

if (Test-Path -LiteralPath $publisher) {
    & $publisher @Arguments
    exit $LASTEXITCODE
}

$python = $env:PUBLISHER_PYTHON
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

& $python -m publisher.cli @Arguments
exit $LASTEXITCODE
