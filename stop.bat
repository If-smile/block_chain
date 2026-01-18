@echo off
chcp 65001 >nul
echo 🛑 正在停止分布式PBFT共识系统...
echo.

REM 查找并停止后端服务（端口8000）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo 🔧 停止后端服务 (PID: %%a)...
    taskkill /F /PID %%a >nul 2>&1
    if errorlevel 1 (
        echo ⚠️  后端服务可能已经停止
    ) else (
        echo ✅ 后端服务已停止
    )
)

REM 查找并停止前端服务（端口3000）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo 🌐 停止前端服务 (PID: %%a)...
    taskkill /F /PID %%a >nul 2>&1
    if errorlevel 1 (
        echo ⚠️  前端服务可能已经停止
    ) else (
        echo ✅ 前端服务已停止
    )
)

REM 检查是否还有进程在运行
netstat -ano | findstr ":8000 :3000" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo.
    echo ✅ 所有服务已成功停止！
) else (
    echo.
    echo ⚠️  仍有服务在运行，请手动检查
)

echo.
pause




