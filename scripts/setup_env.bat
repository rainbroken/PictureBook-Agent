@echo off
chcp 65001 >nul
title Storybook Agent - Setup

rem ==================================================
rem  无论从哪里运行，都切换到项目根目录
rem  当前脚本位于 scripts/ 子目录，所以项目根目录是 scripts 的上一级
rem ==================================================
pushd "%~dp0.."

echo ========================================
echo   Storybook Agent - Setup
echo ========================================
echo Project root: %cd%
echo.

echo [1/5] Checking Python...
python --version
if errorlevel 1 (
echo Python not found. Please install Python 3.10 or 3.11.
pause
popd
exit /b 1
)

echo.
echo [2/5] Checking requirements.txt...
if not exist requirements.txt (
echo requirements.txt not found in project root!
echo Please put requirements.txt here:
echo %cd%\requirements.txt
pause
popd
exit /b 1
)

echo.
echo [3/5] Creating venv in project root...
if not exist venv (
python -m venv venv
) else (
echo venv already exists, skipping.
)

echo.
echo [4/5] Installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
echo Dependency installation failed.
pause
popd
exit /b 1
)

echo.
echo [5/5] Creating output directories...
if not exist storybooks mkdir storybooks
if not exist output mkdir output

echo.
echo ========================================
echo Setup complete!
echo Virtual environment: %cd%\venv
echo Next step: run scripts\run.bat
echo ========================================
pause
popd
