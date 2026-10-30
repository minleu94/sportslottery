Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
currentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

pythonwExe = "pythonw.exe"
If FSO.FileExists("C:\Program Files\Python311\pythonw.exe") Then
    pythonwExe = """C:\Program Files\Python311\pythonw.exe"""
End If

WshShell.Run pythonwExe & " scripts\tray_manager.py", 0, False
