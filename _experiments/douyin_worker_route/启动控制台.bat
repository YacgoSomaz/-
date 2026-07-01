@echo off
setlocal
title 直播间监控控制台
cd /d "%~dp0"
set "PORT=8848"
set "URL=http://127.0.0.1:%PORT%"
echo.
echo   直播间监控控制台
echo   ------------------------------------
echo   地址: %URL%
echo.
rem 探测端口是否已被占用：已在运行就直接开浏览器，避免重复启动绑不上端口而退出
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%PORT%);$c.Close();exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 (
  echo   检测到控制台已在运行，直接打开浏览器。
  echo   如需停止监控，请关掉那个正在运行的黑窗口。
  start %URL%
  echo.
  pause
  exit /b 0
)
where python >nul 2>nul
if errorlevel 1 (
  echo   [错误] 没找到 python 命令，请确认 Python 已安装并加入 PATH。
  echo.
  pause
  exit /b 1
)
echo   正在启动后端... 关闭这个黑窗口即可停止全部监控。
echo.
start "" /min cmd /c "timeout /t 2 >nul & start %URL%"
python -m pipeline.webui --port %PORT%
echo.
echo   控制台已停止。
pause