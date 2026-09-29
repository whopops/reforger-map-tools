# Every export, started by an external program. No prompts.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_export.ps1
# Prefer scripts\run_export.cmd if the caller cannot change execution policy.
param(
    [string]$Map = "everon",
    [string]$Jobs = "buildings,roads,satellite",
    [int]$MaxTiles = 2,
    [string]$Workbench = "",
    [string]$ProfileRoot = "",
    [string]$Image = "",
    [string]$PngDir = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_invoke.ps1"
$runnerArgs = @(
    "--map", $Map,
    "--jobs", $Jobs,
    "--max-tiles", "$MaxTiles"
)
if ($Workbench) { $runnerArgs += @("--workbench", $Workbench) }
if ($ProfileRoot) { $runnerArgs += @("--profile", $ProfileRoot) }
if ($Image) { $runnerArgs += @("--image", $Image) }
if ($PngDir) { $runnerArgs += @("--png-dir", $PngDir) }
Invoke-MapExport $runnerArgs
exit $LASTEXITCODE
