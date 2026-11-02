Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pyExe = "C:\Program Files\Python311\pythonw.exe"
If Not fso.FileExists(pyExe) Then
    pyExe = "pythonw.exe"
End If

WshShell.Run """" & pyExe & """ scripts\tray_manager.py", 0, False
