# scripts/start_dev.ps1
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot
python "$ProjectRoot\scripts\dev_runner.py"
