# Resume a MapExportPlugin job until its status file says done.
# Workbench has to be installed, and this addon has to be the project it opens
# (addon.gproj depends on the game 58D0FB3206B6F859). Confirm the world resource
# in maps/<map>.json in the World Editor before the first run. The usual Everon
# world is worlds/Eden/Eden.ent. A nine-box probe exits 3 and writes nothing if
# the world did not load.
param(
    [Parameter(Mandatory = $true)][ValidateSet("buildings", "roads", "satellite")][string]$Job,
    [string]$Map = "everon",
    [int]$MaxTiles = 2,
    [string]$Workbench = "",
    [string]$ProfileRoot = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$cfgPath = Join-Path $repo "maps\$Map.json"
if (-not (Test-Path $cfgPath)) { throw "No map file $cfgPath" }
$cfg = Get-Content -Raw $cfgPath | ConvertFrom-Json
if (-not $cfg.world) { throw "Set world in $cfgPath after confirming it in the World Editor." }

if (-not $ProfileRoot) {
    $ProfileRoot = Join-Path $env:USERPROFILE "Documents\My Games\ArmaReforgerWorkbench\profile"
}
$statusName = @{ buildings = "export.status.json"; roads = "roads.status.json"; satellite = "satellite.status.json" }[$Job]
$statusPath = Join-Path $ProfileRoot "reforger_map\$Map\$statusName"

$candidates = @($Workbench, $env:ARMA_REFORGER_WORKBENCH)
$candidates += "${env:ProgramFiles(x86)}\Steam\steamapps\common\Arma Reforger Tools\Workbench\ArmaReforgerWorkbenchSteam.exe"
$candidates += "$env:ProgramFiles\Steam\steamapps\common\Arma Reforger Tools\Workbench\ArmaReforgerWorkbenchSteam.exe"
$exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $exe) { throw "ArmaReforgerWorkbenchSteam.exe not found. Pass -Workbench." }

$outArg = '-out=$profile:reforger_map/' + $Map
$previous = $null
$tiles = [Math]::Ceiling([double]$cfg.size / [double]$cfg.tile)
$limit = $tiles * $tiles + 2
for ($launch = 1; $launch -le $limit; $launch++) {
    Write-Host "MapExport $Job launch $launch"
    & $exe "-wbModule=WorldEditor" "-run" "-load" $cfg.world "-plugin=MapExportPlugin" "-job=$Job" "-size=$($cfg.size)" "-tile=$($cfg.tile)" "-buildingStep=$($cfg.buildingStep)" "-maxTiles=$MaxTiles" $outArg
    if ($LASTEXITCODE -eq 3) { throw "World did not load (probe found almost no entities). Nothing was written." }
    if (-not (Test-Path $statusPath)) { throw "No $statusName after Workbench exited $LASTEXITCODE" }
    $status = Get-Content -Raw $statusPath | ConvertFrom-Json
    Write-Host "$($status.result): made $($status.made), skipped $($status.skipped), remaining $($status.remaining)"
    if ($status.result -eq "done") { exit 0 }
    if ($status.result -eq "failed") { exit 1 }
    if ($null -ne $previous -and $status.remaining -ge $previous) { throw "No progress (remaining $($status.remaining))." }
    $previous = $status.remaining
}
throw "Stopped after $limit launches with work still remaining."
