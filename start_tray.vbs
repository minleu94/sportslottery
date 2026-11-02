Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pyExe = "C:\Program Files\Python311\python.exe"
If Not fso.FileExists(pyExe) Then
    pyExe = "python.exe"
End If

' Use the full dev runner so it terminates stale API/tray processes before
' starting the new service. A build-only pass followed by tray_manager.py
' could reuse an old API process with the same APP_BUILD and keep its memory.
WshShell.Run """" & pyExe & """ scripts\dev_runner.py", 0, False
