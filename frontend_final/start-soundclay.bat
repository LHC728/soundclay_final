@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "node_modules\vite\bin\vite.js" (
  echo 正在安装前端依赖，请稍候...
  set NODE_ENV=
  call npm config delete production >nul 2>nul
  call npm config delete omit >nul 2>nul
  call npm install --include=dev
  if errorlevel 1 (
    echo.
    echo 依赖安装失败，请检查网络和 Node.js。
    pause
    exit /b 1
  )
)

echo 正在启动 SoundClay...
node node_modules\vite\bin\vite.js --host 0.0.0.0
pause
