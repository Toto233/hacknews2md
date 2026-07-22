[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$publisher = Join-Path $projectRoot ".venv\Scripts\publisher.exe"

if (-not (Test-Path -LiteralPath $publisher)) {
    throw "Publisher is not installed. Run: python -m pip install -e ."
}

& $publisher @Arguments
exit $LASTEXITCODE
