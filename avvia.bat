@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Prima installa le dipendenze come indicato nel README.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
pause
