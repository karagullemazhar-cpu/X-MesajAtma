@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    call "%~dp0KUR.bat"
)

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo.
    echo  HATA: Calisma ortami bulunamadi. Lutfen KUR.bat dosyasina cift tiklayin.
    echo.
    pause
    exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0xpost.py"
