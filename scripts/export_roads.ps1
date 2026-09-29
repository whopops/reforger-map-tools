# Rerun Workbench until every road tile is done. Dirt pieces and bridge decks are included.
param(
    [string]$Map = "everon",
    [int]$MaxTiles = 2,
    [string]$Workbench = "",
    [string]$ProfileRoot = ""
)
& "$PSScriptRoot\export_job.ps1" -Job roads -Map $Map -MaxTiles $MaxTiles -Workbench $Workbench -ProfileRoot $ProfileRoot
exit $LASTEXITCODE
