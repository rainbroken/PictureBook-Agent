@echo off
chcp 65001 >nul
title 绘本工坊 - 环境安装

echo ========================================
echo   绘本工坊 Storybook Agent 环境安装
echo ========================================

echo.
echo [1/4] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo 未检测到 Python，请先安装 Python 3.10 或 3.11
    pause
    exit /b
)

echo.
echo [2/4] 创建虚拟环境 venv...
if not exist venv (
    python -m venv venv
) else (
    echo venv 已存在，跳过创建
)

echo.
echo [3/4] 激活虚拟环境并安装依赖...
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [4/4] 创建输出目录...
if not exist storybooks (
    mkdir storybooks
)

echo.
echo ========================================
echo 环境安装完成！
echo 请复制 .env.example 为 .env，并填写 API Key
echo 然后双击 run.bat 启动项目
echo ========================================
pause