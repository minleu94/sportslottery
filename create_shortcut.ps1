$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = [Environment]::GetFolderPath('StartMenu')
$projDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbsTarget = Join-Path $projDir "start_tray.vbs"
$iconPath = (Join-Path $projDir "app_icon.ico") + ",0"

# 1. Desktop shortcut (zero popup / zero window resident launch)
$desktopLnk = Join-Path $desktop "台灣運彩瘋狗流.lnk"
$sc1 = $ws.CreateShortcut($desktopLnk)
$sc1.TargetPath = "wscript.exe"
$sc1.Arguments = "`"$vbsTarget`""
$sc1.WorkingDirectory = $projDir
$sc1.IconLocation = $iconPath
$sc1.Description = "台灣運彩「瘋狗流」決策系統 (v2.3.0 Dev)"
$sc1.Save()
Write-Host "Created Desktop shortcut: $desktopLnk"

# 2. Start Menu shortcut
$startMenuPrograms = Join-Path $startMenu "Programs"
$startMenuLnk = Join-Path $startMenuPrograms "台灣運彩瘋狗流.lnk"
$sc2 = $ws.CreateShortcut($startMenuLnk)
$sc2.TargetPath = "wscript.exe"
$sc2.Arguments = "`"$vbsTarget`""
$sc2.WorkingDirectory = $projDir
$sc2.IconLocation = $iconPath
$sc2.Description = "台灣運彩「瘋狗流」決策系統 (v2.3.0 Dev)"
$sc2.Save()
Write-Host "Created Start Menu shortcut: $startMenuLnk"
