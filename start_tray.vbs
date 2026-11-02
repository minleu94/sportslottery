Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pyExe = "C:\Program Files\Python311\python.exe"
If Not fso.FileExists(pyExe) Then
    pyExe = "python.exe"
End If

buildExitCode = WshShell.Run("""" & pyExe & """ scripts\dev_runner.py --build-only", 0, True)
If buildExitCode <> 0 Then
    MsgBox "前端更新失敗，請查看開發環境後再重新啟動。", vbCritical, "瘋狗流開發啟動失敗"
    WScript.Quit buildExitCode
End If

pywExe = "C:\Program Files\Python311\pythonw.exe"
If Not fso.FileExists(pywExe) Then
    pywExe = "pythonw.exe"
End If

WshShell.Run """" & pywExe & """ scripts\tray_manager.py", 0, False
