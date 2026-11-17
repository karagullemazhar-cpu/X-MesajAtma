@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title X-MesajAtma - Kurulum
cd /d "%~dp0"

echo.
echo  ==================================================
echo    X-MesajAtma - Otomatik Kurulum
echo  ==================================================
echo.
echo    Bu pencere her seyi kendisi yapar.
echo    Kurulum bitene kadar KAPATMAYIN.
echo.

set "PYEXE="

rem ---------- 1) Python arama ----------
echo  [1/4] Python araniyor...

for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE goto :python_var

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" set "PYEXE=%%~fD\python.exe"
)
if defined PYEXE goto :python_var

for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do (
    if not defined PYEXE set "PYEXE=%%P"
)
if defined PYEXE goto :python_var

rem ---------- 2) Python yoksa kur ----------
echo  Python bulunamadi, otomatik kurulacak (1-3 dakika)...
where winget >nul 2>&1
if errorlevel 1 goto :python_elle

winget install -e --id Python.Python.3.12 --scope user --silent ^
  --accept-package-agreements --accept-source-agreements
if errorlevel 1 echo  Otomatik kurulum basarisiz oldu, elle kurulum gerekiyor.

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" set "PYEXE=%%~fD\python.exe"
)
if defined PYEXE goto :python_var

:python_elle
echo.
echo  --------------------------------------------------
echo   Python kurulu degil ve otomatik kurulamadi.
echo.
echo   1) Acilacak sayfadan Python'u indirip kurun:
echo      https://www.python.org/downloads/
echo   2) Kurulum ekraninda "Add python.exe to PATH"
echo      kutusunu ISARETLEYIN.
echo   3) Sonra bu KUR.bat dosyasina tekrar cift tiklayin.
echo  --------------------------------------------------
echo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:python_var
echo        Python bulundu: %PYEXE%

rem ---------- 3) Sanal ortam + paketler ----------
echo  [2/4] Calisma ortami hazirlaniyor...
if not exist "%~dp0.venv\Scripts\python.exe" (
    "%PYEXE%" -m venv "%~dp0.venv"
)
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo  HATA: Calisma ortami olusturulamadi.
    echo  Cozum: Python'u kaldirip https://www.python.org/downloads/
    echo  adresinden yeniden kurun ve tekrar deneyin.
    pause
    exit /b 1
)

echo  [3/4] Gerekli paketler yukleniyor (internet gerekir)...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" --quiet --disable-pip-version-check

"%~dp0.venv\Scripts\python.exe" -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  HATA: Paketler yuklenemedi. Internet baglantisini kontrol edip
    echo  KUR.bat dosyasina tekrar cift tiklayin.
    pause
    exit /b 1
)

rem ---------- 4) Masaustu simgesi ----------
echo  [4/4] Masaustu simgesi olusturuluyor...
if "%XMA_KURULUM_TESTI%"=="1" goto :bitti

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$w=New-Object -ComObject WScript.Shell;" ^
 "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'X-MesajAtma.lnk';" ^
 "$s=$w.CreateShortcut($p);" ^
 "$s.TargetPath='%~dp0BASLAT.bat';" ^
 "$s.WorkingDirectory='%~dp0';" ^
 "$s.IconLocation='%SystemRoot%\System32\shell32.dll,220';" ^
 "$s.Description='X-MesajAtma - canli mesaj paneli';" ^
 "$s.Save();" ^
 "Write-Host '        Masaustune X-MesajAtma simgesi eklendi.'" >nul 2>&1

:bitti
echo.
echo  ==================================================
echo    KURULUM TAMAM
echo  ==================================================
echo.
echo    NASIL CALISTIRILIR:
echo.
echo    1) Masaustundeki "X-MesajAtma" simgesine
echo       cift tiklayin.  (Simge yoksa bu klasordeki
echo       BASLAT.bat dosyasina cift tiklayin.)
echo.
echo    2) Tarayici kendiliginden acilir. Acilmazsa
echo       tarayiciya su adresi yazin:
echo           http://127.0.0.1:5077
echo.
echo    3) Kapatmak icin acilan siyah pencereyi kapatin.
echo.
echo    NOT: Panel sadece bu bilgisayarda acilir.
echo         Baska cihazdan izlemek isterseniz README
echo         dosyasindaki "Telefondan izleme" bolumune
echo         bakin.
echo.
echo  ==================================================
echo.
if "%XMA_KURULUM_TESTI%"=="1" goto :son
pause
:son
endlocal
