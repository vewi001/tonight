@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tonight
echo.
echo Подготавливаем Tonight...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :python_error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :install_error
".venv\Scripts\python.exe" launcher.py
goto :end

:python_error
echo.
echo Не найден Python 3.11 или новее. Установите Python с python.org и включите Add Python to PATH.
pause
goto :end

:install_error
echo.
echo Не удалось установить зависимости. Проверьте интернет при первом запуске и попробуйте снова.
pause

:end

