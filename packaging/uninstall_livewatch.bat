@echo off
setlocal
title 复盘虾 Uninstall Shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_livewatch.ps1"

