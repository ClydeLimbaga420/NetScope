@echo off
rem cmd.exe does not wait for GUI programs at an interactive prompt.
rem Running the windowed exe from a batch file keeps CLI output before the next prompt.
set "NETSCOPE_EXE=%~dp0..\NetScope.exe"
if not exist "%NETSCOPE_EXE%" set "NETSCOPE_EXE=%~dp0NetScope.exe"
"%NETSCOPE_EXE%" %*
exit /b %ERRORLEVEL%
