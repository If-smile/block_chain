@echo off
chcp 65001
echo ========================================
echo 启动调试模式 - 查看详细错误信息
echo ========================================
echo.

echo [1/4] 检查Python环境...
python --version
if errorlevel 1 (
    echo ❌ Python未安装或不在PATH中
    pause
    exit /b 1
)
echo ✅ Python检查通过
echo.

echo [2/4] 检查Node.js环境...
node --version
if errorlevel 1 (
    echo ❌ Node.js未安装或不在PATH中
    pause
    exit /b 1
)
echo ✅ Node.js检查通过
echo.

echo [3/4] 检查依赖...
if not exist "node_modules" (
    echo ⚠️  前端依赖未安装，正在安装...
    call npm install
    if errorlevel 1 (
        echo ❌ 前端依赖安装失败
        pause
        exit /b 1
    )
) else (
    echo ✅ 前端依赖已存在
)

if not exist "backend\__pycache__" (
    echo ⚠️  后端依赖可能未安装，正在检查...
    cd backend
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ 后端依赖安装失败
        cd ..
        pause
        exit /b 1
    )
    cd ..
) else (
    echo ✅ 后端依赖已存在
)
echo.

echo [4/4] 启动服务...
echo.
echo 正在启动后端服务（端口8000）...
cd backend
start "PBFT后端服务-调试" cmd /k "python main.py"
cd ..
timeout /t 3 /nobreak >nul

echo 检查后端服务状态...
netstat -ano | findstr ":8000" | findstr "LISTENING"
if errorlevel 1 (
    echo ❌ 后端服务启动失败！请查看"PBFT后端服务-调试"窗口的错误信息
) else (
    echo ✅ 后端服务已启动
)

echo.
echo 正在启动前端服务（端口3000）...
start "PBFT前端服务-调试" cmd /k "npm run dev"
timeout /t 5 /nobreak >nul

echo 检查前端服务状态...
netstat -ano | findstr ":3000" | findstr "LISTENING"
if errorlevel 1 (
    echo ❌ 前端服务启动失败！请查看"PBFT前端服务-调试"窗口的错误信息
) else (
    echo ✅ 前端服务已启动
)

echo.
echo ========================================
echo 启动完成！
echo.
echo 如果服务未启动，请查看上面打开的两个窗口中的错误信息
echo 前端地址: http://localhost:3000
echo 后端地址: http://localhost:8000
echo ========================================
echo.
pause




