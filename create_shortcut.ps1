$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = [Environment]::GetFolderPath('StartMenu')
$projDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetExe = Join-Path $projDir "sportslottery.exe"
$iconPath = (Join-Path $projDir "app_icon.ico") + ",0"

# 1. Desktop shortcut
$desktopLnk = Join-Path $desktop "sportslottery.lnk"
$sc1 = $ws.CreateShortcut($desktopLnk)
$sc1.TargetPath = $targetExe
$sc1.WorkingDirectory = $projDir
$sc1.IconLocation = $iconPath
$sc1.Description = "台灣運彩「瘋狗流」決策系統 (Modern Edition)"
$sc1.Save()
Write-Host "Created Desktop shortcut: $desktopLnk"

# 2. Start Menu shortcut
$startMenuPrograms = Join-Path $startMenu "Programs"
$startMenuLnk = Join-Path $startMenuPrograms "sportslottery.lnk"
$sc2 = $ws.CreateShortcut($startMenuLnk)
$sc2.TargetPath = $targetExe
$sc2.WorkingDirectory = $projDir
$sc2.IconLocation = $iconPath
$sc2.Description = "台灣運彩「瘋狗流」決策系統 (Modern Edition)"
$sc2.Save()
Write-Host "Created Start Menu shortcut: $startMenuLnk"
