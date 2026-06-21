@echo off
chcp 65001 >nul
title Storybook Agent - Run

rem ==================================================
rem  无论从哪里运行，都切换到项目根目录
rem ==================================================
pushd "%~dp0.."

echo ========================================
echo   Storybook Agent - Launcher
echo ========================================
echo Project root: %cd%
echo.

echo [1/4] Checking venv...
if not exist venv (
echo venv not found in project root.
echo Please run scripts\setup_env.bat first.
pause
popd
exit /b 1
)

echo.
echo [2/4] Activating venv...
call venv\Scripts\activate.bat

if errorlevel 1 (
echo Failed to activate venv.
pause
popd
exit /b 1
)

echo.
echo [3/4] Checking Flask...
python -c "import flask; print('Flask OK')"
if errorlevel 1 (
echo Flask is not installed.
echo Please run scripts\setup_env.bat again.
pause
popd
exit /b 1
)

echo.
echo [4/4] Starting Web server...
echo Visit: http://127.0.0.1:5001
echo.

python app\collect_input_web.py

pause
popd
