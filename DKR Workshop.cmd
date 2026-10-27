@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -B -m src.main %*
) else (
    python -B -m src.main %*
)
if errorlevel 1 pause
