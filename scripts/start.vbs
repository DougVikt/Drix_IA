Set Shell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
root = FSO.GetParentFolderName(WScript.ScriptFullName) & "\..\"
root = FSO.GetAbsolutePathName(root) & "\"

Shell.CurrentDirectory = root
Shell.Environment("PROCESS")("OLLAMA_MODELS") = root & "ia_system\models"
Shell.Environment("PROCESS")("PATH") = root & "ia_system\python\python-3.10.11.amd64;" & root & "ia_system\engine;" & Shell.Environment("PROCESS")("PATH")

Shell.Run root & "ia_system\engine\ollama.exe serve", 0, False
WScript.Sleep 5000
Shell.Run root & ".venv\Scripts\pythonw.exe scripts\start.py", 1, True
Shell.Run "taskkill /f /im ollama.exe", 0, False
