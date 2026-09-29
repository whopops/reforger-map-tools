# Shared starter. Dot-source this; it does not run a job by itself.
function Invoke-MapExport([string[]]$RunnerArgs) {
    $repo = Split-Path $PSScriptRoot -Parent
    $runner = Join-Path $repo "py\run_export.py"
    $py = @("python", "python3", "py") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
    if (-not $py) {
        Write-Error "python not found"
        exit 2
    }
    $argv = @()
    if ($py -eq "py") { $argv += "-3" }
    $argv += $runner
    $argv += $RunnerArgs
    & $py @argv
}
