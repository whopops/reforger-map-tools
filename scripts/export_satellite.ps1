# Rerun Workbench until every satellite shot is taken, then stop.
# Set the editor camera fov to 15 and the far plane above the height the plugin prints.
# Then:  python py/make_tiles.py --shots "<profile>/reforger_map/everon/satellite" --out tiles
param(
    [string]$Map = "everon",
    [int]$MaxTiles = 2,
    [string]$Workbench = "",
    [string]$ProfileRoot = ""
)
& "$PSScriptRoot\export_job.ps1" -Job satellite -Map $Map -MaxTiles $MaxTiles -Workbench $Workbench -ProfileRoot $ProfileRoot
exit $LASTEXITCODE
