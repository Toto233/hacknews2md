$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("hacknews-install-test-" + [guid]::NewGuid())
$codexHome = Join-Path $tempRoot ".codex"

try {
    & (Join-Path $repoRoot "install.ps1") -CodexHome $codexHome -DryRun
    if (Test-Path -LiteralPath (Join-Path $codexHome "skills\publish-hacknews-codex")) {
        throw "DryRun unexpectedly created the skill target"
    }

    $oldTarget = Join-Path $codexHome "skills\publish-hacknews-codex"
    New-Item -ItemType Directory -Force -Path $oldTarget | Out-Null
    Set-Content -LiteralPath (Join-Path $oldTarget "old-skill.txt") -Value "preserved"

    & (Join-Path $repoRoot "install.ps1") -CodexHome $codexHome
    $target = Join-Path $codexHome "skills\publish-hacknews-codex"
    $item = Get-Item -LiteralPath $target -Force
    if ($item.LinkType -ne "Junction") {
        throw "Expected Junction, got: $($item.LinkType)"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $target "SKILL.md"))) {
        throw "Installed Junction cannot access SKILL.md"
    }
    $backups = @(Get-ChildItem -LiteralPath (Join-Path $codexHome "skills") -Directory -Filter "publish-hacknews-codex.backup_*")
    if ($backups.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $backups[0].FullName "old-skill.txt"))) {
        throw "Existing skill was not preserved in a timestamped backup"
    }

    & (Join-Path $repoRoot "install.ps1") -CodexHome $codexHome
    $secondItem = Get-Item -LiteralPath $target -Force
    if ($secondItem.LinkType -ne "Junction") {
        throw "Repeated install replaced the Junction unexpectedly"
    }
    Write-Host "Installer test passed: $target"
} finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path $resolvedTemp)) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}
