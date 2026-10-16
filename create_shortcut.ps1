$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$projDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$lnkPath = Join-Path $desktop "sportslottery.lnk"
$shortcut = $ws.CreateShortcut($lnkPath)
$shortcut.TargetPath = Join-Path $projDir "sportslottery.exe"
$shortcut.WorkingDirectory = $projDir
$shortcut.IconLocation = (Join-Path $projDir "app_icon.ico") + ",0"
$shortcut.Description = "Sports Lottery System"
$shortcut.Save()
Write-Host "Created shortcut: $lnkPath"
