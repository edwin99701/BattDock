Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appScript = fso.BuildPath(scriptDir, "mouse_battery_app.py")
localPyw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe")
If fso.FileExists(localPyw) Then
    pythonw = localPyw
Else
    pythonw = "pythonw.exe"
End If
shell.Run """" & pythonw & """ """ & appScript & """", 0, False
