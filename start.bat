@echo off
title SHUCLAW
cd /d "%~dp0"

rem Keep Python's files in a short path: the controller driver library fails to load from long paths
set "VENV=%LOCALAPPDATA%\SHUCLAW\venv"

if not exist "%VENV%\Scripts\python.exe" (
    echo First run: setting up SHUCLAW, this takes a minute...
    python -m venv "%VENV%" || (echo Python not found. Install it from python.org & pause & exit /b 1)
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)

"%VENV%\Scripts\python.exe" server.py %*
pause
