@echo off
rem Builds dist\SHUCLAW.exe: one file, no console window, nothing else to install except the ViGEmBus driver.
title Building SHUCLAW.exe
cd /d "%~dp0"

set "BVENV=%LOCALAPPDATA%\SHUCLAW\build-venv"
if not exist "%BVENV%\Scripts\python.exe" (
    python -m venv "%BVENV%" || (echo Python not found. Install it from python.org & pause & exit /b 1)
)
"%BVENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%BVENV%\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || (pause & exit /b 1)

rem App icon, drawn by the same code as the tray icon
"%BVENV%\Scripts\python.exe" -c "import shuclaw_app; shuclaw_app.make_icon(256).save('shuclaw.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" || (pause & exit /b 1)

"%BVENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name SHUCLAW --icon "%~dp0shuclaw.ico" ^
    --add-data "%~dp0static;static" ^
    --collect-all vgamepad ^
    --hidden-import pystray._win32 ^
    --workpath "%LOCALAPPDATA%\SHUCLAW\build" --specpath "%LOCALAPPDATA%\SHUCLAW\build" ^
    SHUCLAW.pyw || (pause & exit /b 1)

echo.
echo Done: dist\SHUCLAW.exe
pause
