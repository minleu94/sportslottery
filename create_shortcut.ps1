$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = [Environment]::GetFolderPath('Programs')
$projDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projDir "sportslottery.exe"
$iconPath = (Join-Path $projDir "app_icon.ico") + ",0"

# 1. Desktop shortcut
$deskLnk = Join-Path $desktop "sportslottery.lnk"
$s1 = $ws.CreateShortcut($deskLnk)
$s1.TargetPath = $exePath
$s1.WorkingDirectory = $projDir
$s1.IconLocation = $iconPath
$s1.Description = "台灣運彩瘋狗流 3-in-1 全功能系統匣常駐決策台"
$s1.Save()
Write-Host "Created Desktop shortcut: $deskLnk"

# 2. Start Menu shortcut
$startLnk = Join-Path $startMenu "sportslottery.lnk"
$s2 = $ws.CreateShortcut($startLnk)
$s2.TargetPath = $exePath
$s2.WorkingDirectory = $projDir
$s2.IconLocation = $iconPath
$s2.Description = "台灣運彩瘋狗流 3-in-1 全功能系統匣常駐決策台"
$s2.Save()
Write-Host "Created Start Menu shortcut: $startLnk"
