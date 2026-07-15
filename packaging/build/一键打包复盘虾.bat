@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"

> "%~dp0build-launch.log" echo Build launch requested. Open build-last.log for the result.
start "LiveWatch Official Build" pwsh.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0interactive_verified_release.ps1"
exit /b 0
