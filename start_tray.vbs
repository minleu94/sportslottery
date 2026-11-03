Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

logDir = WshShell.ExpandEnvironmentStrings("%SPORTSLOTTERY_LOG_DIR%")
If logDir = "%SPORTSLOTTERY_LOG_DIR%" Or logDir = "" Then
    localAppData = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    If localAppData = "%LOCALAPPDATA%" Then
        localAppData = WshShell.ExpandEnvironmentStrings("%TEMP%")
    End If
    appLogDir = fso.BuildPath(localAppData, "Sportslottery")
    If Not fso.FolderExists(appLogDir) Then
        fso.CreateFolder(appLogDir)
    End If
    logDir = fso.BuildPath(appLogDir, "logs")
End If
If Not fso.FolderExists(logDir) Then
    fso.CreateFolder(logDir)
End If
launcherLogPath = fso.BuildPath(logDir, "start_tray_launcher.log")
Set launcherLog = fso.OpenTextFile(launcherLogPath, 8, True)
launcherLog.WriteLine "Tray launcher started."

pyExe = "C:\Program Files\Python311\python.exe"
If Not fso.FileExists(pyExe) Then
    pyExe = "python.exe"
End If
launcherLog.WriteLine "Selected Python executable: " & pyExe
launcherLog.Close

' Keep this hidden wrapper alive for the Tray lifetime so the Python exit code
' or a launch exception is recorded even when the user starts from the .bat file.
On Error Resume Next
exitCode = WshShell.Run("""" & pyExe & """ -u """ & scriptDir & "\scripts\dev_runner.py""", 0, True)
launchError = Err.Number
launchDescription = Err.Description
Err.Clear
On Error GoTo 0

Set launcherLog = fso.OpenTextFile(launcherLogPath, 8, True)
If launchError <> 0 Then
    launcherLog.WriteLine "Failed to launch dev_runner. Error " & CStr(launchError) & ": " & launchDescription
Else
    launcherLog.WriteLine "dev_runner exited with code " & CStr(exitCode) & "."
End If
launcherLog.Close
