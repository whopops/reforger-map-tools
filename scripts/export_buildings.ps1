# Rerun Workbench until every building tile is done. Default 2 new tiles a launch.
param(
    [string]$Map = "everon",
    [int]$MaxTiles = 2,
    [string]$Workbench = "",
    [string]$ProfileRoot = ""
)
& "$PSScriptRoot\export_job.ps1" -Job buildings -Map $Map -MaxTiles $MaxTiles -Workbench $Workbench -ProfileRoot $ProfileRoot
exit $LASTEXITCODE
