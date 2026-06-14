@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (
  echo Trusted Windows PowerShell executable not found: "%POWERSHELL_EXE%" 1>&2
  exit /b 1
)
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install_local.ps1" %*
exit /b %ERRORLEVEL%
