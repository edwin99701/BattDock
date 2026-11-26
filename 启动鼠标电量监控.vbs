Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appPath = scriptDir & "\mouse_battery_app.py"
pythonw = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

Set shell = CreateObject("WScript.Shell")
shell.Run """" & pythonw & """ """ & appPath & """", 0, False
