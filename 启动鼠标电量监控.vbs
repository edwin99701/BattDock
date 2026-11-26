Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appPath = scriptDir & "\mouse_battery_app.py"
localAppData = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
pythonw = localAppData & "\Programs\Python\Python312\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

shell.Run """" & pythonw & """ """ & appPath & """", 0, False
