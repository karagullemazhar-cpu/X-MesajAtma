@echo off
chcp 65001 >nul 2>&1
title X-MesajAtma
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo   Once KUR.bat dosyasina cift tiklayin.
    echo.
    pause
    exit /b 1
)

echo.
echo   X-MesajAtma baslatiliyor...
echo   Panel: http://127.0.0.1:5077
echo.
echo   Bu pencereyi KAPATMAYIN. Kapatirsaniz panel durur.
echo.

set "XMA_AC=1"
"%~dp0.venv\Scripts\python.exe" app.py

echo.
echo   Uygulama durdu.
pause
