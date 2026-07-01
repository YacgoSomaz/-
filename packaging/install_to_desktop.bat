@echo off
setlocal
title 直播复盘侠 Install
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_to_desktop.ps1"

