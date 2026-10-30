# packaging/windows/build_windows.ps1
# Automated Windows build script: Runs PyInstaller and builds portable ZIP / Inno Setup installer.

param(
    [string]$Version = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot

if (-not $Version -and $env:GITHUB_REF_NAME) {
    $Version = $env:GITHUB_REF_NAME.TrimStart('v')
}
if (-not $Version) {
    $Version = "2.2.0"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Taiwan Sports Lottery - Windows 11 Build Pipeline" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$DistDir = "$ProjectRoot\dist\Sportslottery"
$InstallerDir = "$ProjectRoot\dist\installer"

if (-not (Test-Path $InstallerDir)) {
    New-Item -ItemType Directory -Path $InstallerDir -Force | Out-Null
}

# 1. Run PyInstaller if not already built or build requested
if (-not (Test-Path "$DistDir\Sportslottery.exe")) {
    Write-Host "[1/3] Running PyInstaller..." -ForegroundColor Yellow
    python -m PyInstaller --clean --noconfirm "$ProjectRoot\sportslottery_dist.spec"
    if (-not (Test-Path "$DistDir\Sportslottery.exe")) {
        Write-Host "Build failed: Sportslottery.exe not found." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[1/3] PyInstaller bundle already present at $DistDir" -ForegroundColor Green
}

# 2. Create Portable Zip
Write-Host "[2/3] Generating Portable ZIP package (v$Version)..." -ForegroundColor Yellow
$ZipPath = "$InstallerDir\Sportslottery_Win11_Portable_v$Version.zip"
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Compress-Archive -Path "$DistDir\*" -DestinationPath $ZipPath
Write-Host "Portable package created: $ZipPath" -ForegroundColor Green

# 3. Check for Inno Setup compiler (iscc)
Write-Host "[3/3] Checking for Inno Setup compiler..." -ForegroundColor Yellow
$isccCandidates = @(
    "iscc",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$isccPath = $null
foreach ($c in $isccCandidates) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
        $isccPath = $c
        break
    } elseif (Test-Path $c) {
        $isccPath = $c
        break
    }
}

if ($isccPath -and -not $SkipInstaller) {
    Write-Host "Inno Setup found ($isccPath). Compiling Setup.exe (v$Version)..." -ForegroundColor Cyan
    & $isccPath "/DMyAppVersion=$Version" "$ProjectRoot\packaging\windows\installer.iss"
    Write-Host "Setup installer created in: $InstallerDir" -ForegroundColor Green
} else {
    Write-Host "Notice: Inno Setup compiler not found locally." -ForegroundColor Gray
    Write-Host "The Portable ZIP package is ready to distribute to your friends!" -ForegroundColor Green
    Write-Host "(For Setup.exe, push to GitHub Actions to compile in the cloud automatically)" -ForegroundColor Gray
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Build Finished! Output Directory: $InstallerDir" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
