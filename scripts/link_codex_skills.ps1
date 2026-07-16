param(
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourceRoot = Join-Path $repoRoot "skills"
$destRoot = Join-Path $repoRoot ".codex\skills"

if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Project skills directory not found: $sourceRoot"
}

New-Item -ItemType Directory -Force -Path $destRoot | Out-Null
$destRootResolved = (Resolve-Path -LiteralPath $destRoot).Path

Get-ChildItem -LiteralPath $sourceRoot -Directory | ForEach-Object {
    $source = $_.FullName
    $dest = Join-Path $destRootResolved $_.Name
    if (-not $dest.StartsWith($destRootResolved, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside .codex skills: $dest"
    }

    if (Test-Path -LiteralPath $dest) {
        $existing = Get-Item -LiteralPath $dest -Force
        if ($existing.LinkType -in @("Junction", "SymbolicLink")) {
            if ($existing.Target -contains $source) {
                Write-Output "Already linked: $dest -> $source"
                return
            }
            if (-not $Replace) {
                throw "Existing link points elsewhere: $dest. Rerun with -Replace to recreate it."
            }
            Remove-Item -LiteralPath $dest -Force
        } else {
            if (-not $Replace) {
                throw "Existing non-link skill directory: $dest. Rerun with -Replace to replace it with a junction."
            }
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
    }

    New-Item -ItemType Junction -Path $dest -Target $source | Out-Null
    Write-Output "Linked: $dest -> $source"
}
