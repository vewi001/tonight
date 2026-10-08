@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tonight - постеры
if not exist ".venv\Scripts\python.exe" (
  echo Сначала один раз запустите start.bat.
  pause
  exit /b 1
)
echo Докачиваем постеры и фоны для всего каталога. Это может занять несколько минут...
".venv\Scripts\python.exe" scripts\cache_catalog_images.py
if errorlevel 1 (
  echo Не удалось докачать изображения. Проверьте интернет и попробуйте снова.
  pause
  exit /b 1
)
echo Готово. Теперь можно запускать Tonight.
pause
