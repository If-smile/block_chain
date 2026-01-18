@echo off
chcp 65001 >nul
echo 🚀 启动分布式PBFT共识系统...
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python 未安装，请先安装Python
    pause
    exit /b 1
)

REM 检查Node.js是否安装
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js 未安装，请先安装Node.js
    pause
    exit /b 1
)

REM 检查npm是否安装
npm --version >nul 2>&1
if errorlevel 1 (
    echo ❌ npm 未安装，请先安装npm
    pause
    exit /b 1
)

echo 📦 检查依赖...
if not exist "node_modules" (
    echo 📦 安装前端依赖...
    call npm install
)

if not exist "backend\__pycache__" (
    echo 🐍 安装后端依赖...
    cd backend
    pip install -r requirements.txt
    cd ..
)

echo.
echo 🔧 启动后端服务...
cd backend
start "PBFT后端服务" cmd /k "python main.py"
cd ..

echo ⏳ 等待后端服务启动...
timeout /t 5 /nobreak >nul

REM 检查后端是否启动成功
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo ⚠️  警告: 后端服务可能未成功启动，请检查后端服务窗口的错误信息
) else (
    echo ✅ 后端服务已启动
)

echo.
echo 🌐 启动前端服务...
start "PBFT前端服务" cmd /k "npm run dev"

echo ⏳ 等待前端服务启动...
timeout /t 5 /nobreak >nul

REM 检查前端是否启动成功
netstat -ano | findstr ":3000" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo ⚠️  警告: 前端服务可能未成功启动，请检查前端服务窗口的错误信息
) else (
    echo ✅ 前端服务已启动
)

echo.
echo ========================================
echo ✅ 系统启动完成！
echo 📱 前端地址: http://localhost:3000
echo 🔧 后端地址: http://localhost:8000
echo ========================================
echo.
echo 两个服务窗口已打开，请查看是否有错误信息
echo 如果服务未启动，请检查服务窗口中的错误提示
echo.
echo 按任意键退出此窗口（服务窗口会继续运行）...
pause

