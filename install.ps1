[CmdletBinding()]
param(
    [string]$CodexHome = $env:CODEX_HOME,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$source = Join-Path $repoRoot "skills\publish-hacknews-codex"
if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
    throw "Repository skill source not found: $source"
}

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    $CodexHome = Join-Path $HOME ".codex"
}
$CodexHome = [System.IO.Path]::GetFullPath($CodexHome)
$skillsDir = Join-Path $CodexHome "skills"
$target = Join-Path $skillsDir "publish-hacknews-codex"

Write-Host "Repository: $repoRoot"
Write-Host "Skill source: $source"
Write-Host "Codex skill target: $target"

if (Test-Path -LiteralPath $target) {
    $existing = Get-Item -LiteralPath $target -Force
    $existingTarget = $null
    if ($existing.LinkType -eq "Junction" -or $existing.LinkType -eq "SymbolicLink") {
        $existingTarget = [System.IO.Path]::GetFullPath([string]$existing.Target)
    }
    if ($existingTarget -and $existingTarget.TrimEnd('\') -eq $source.TrimEnd('\')) {
        Write-Host "Skill is already linked to this repository."
        exit 0
    }

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backup = "$target.backup_$timestamp"
    if ($DryRun) {
        Write-Host "[DryRun] Would move existing skill to: $backup"
    } else {
        try {
            Move-Item -LiteralPath $target -Destination $backup
        } catch {
            throw "Existing skill is locked by an active Codex process. Close/restart Codex, then rerun install.ps1. No files were changed. Original error: $($_.Exception.Message)"
        }
        Write-Host "Existing skill backed up to: $backup"
    }
}

if ($DryRun) {
    Write-Host "[DryRun] Would create Junction: $target -> $source"
    exit 0
}

New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host "Installed publish-hacknews-codex as a Junction."
