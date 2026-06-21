@echo off
chcp 65001 >nul
title 绘本工坊 - 一键启动

echo ========================================
echo   绘本工坊 Storybook Agent
echo   一键启动脚本
echo ========================================

echo.
echo [1/5] 检查虚拟环境...
if not exist venv (
    echo 未检测到 venv，请先运行 setup_env.bat
    pause
    exit /b
)

echo.
echo [2/5] 激活虚拟环境...
call venv\Scripts\activate

echo.
echo [3/5] 检查配置文件...
if not exist config\config.yaml (
    echo 未找到 config\config.yaml！
    echo 请检查 config 目录是否存在
    pause
    exit /b
)
echo 配置文件已找到

echo.
echo [4/5] 检查运行环境...
python -c "from config import load_config; cfg=load_config(); print('  config OK, keys:', list(cfg.keys()))" 2>nul
if errorlevel 1 (
    echo 配置加载失败，请检查 config/config.yaml 格式
    pause
    exit /b
)

echo.
echo [5/5] 启动 Web 服务...
echo 启动成功后，请访问：
echo http://127.0.0.1:5001
echo.

python app\collect_input_web.py

pause