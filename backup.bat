@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "data\tonight.db" (
  echo База Tonight пока не создана.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\backup_db.py
if errorlevel 1 (
  echo Не удалось создать резервную копию.
  pause
  exit /b 1
)
echo Резервная копия готова: data\backups
pause

