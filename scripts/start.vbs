' Drix - inicializador silencioso (sem console).
' Para ver o menu e mensagens de erro, use start.bat.
Set Shell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

root = FSO.GetParentFolderName(WScript.ScriptFullName) & "\..\"
root = FSO.GetAbsolutePathName(root) & "\"
Shell.CurrentDirectory = root

Shell.Environment("PROCESS")("OLLAMA_MODELS") = root & "ia_system\models"
Shell.Environment("PROCESS")("PYTHONPATH") = root & ".venv\Lib\site-packages"
Shell.Environment("PROCESS")("PATH") = root & "ia_system\python\python-3.10.11.amd64;" & root & "ia_system\engine;" & root & "ia_system\bin;" & Shell.Environment("PROCESS")("PATH")

py = root & "ia_system\python\python-3.10.11.amd64\pythonw.exe"
cmd = """" & py & """ """ & root & "scripts\service.py"" web"
Shell.Run cmd, 0, False