@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
title X-MesajAtma - Otomatik Kurulum
cd /d "%~dp0"

echo.
echo  ==========================================================
echo    X-MesajAtma (X Poster) - Tam Otomatik Kurulum
echo  ==========================================================
echo.
echo    Bu pencere gereken tum bilesenleri kendisi indirip kurar:
echo    Python 3.13, Chrome, sesle yazma modeli ve masaustu simgesi.
echo    Lutfen kurulum bitene kadar pencereyi KAPATMAYIN.
echo.

set "PYEXE="

rem ---------- [1/6] Python 3.13+ ve Tkinter kontrolu ----------
echo  [1/6] Python 3.13 ve arayuz destegi araniyor...

for /f "delims=" %%P in ('py -3.13 -c "import sys, tkinter; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE goto :python_var

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if defined PYEXE goto :python_var

for /f "delims=" %%P in ('py -3 -c "import sys, tkinter; assert sys.version_info >= (3,11); print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE goto :python_var

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python31*") do (
    if not defined PYEXE if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -c "import tkinter" >nul 2>&1
        if not errorlevel 1 set "PYEXE=%%~fD\python.exe"
    )
)
if defined PYEXE goto :python_var

echo        Python 3.13 bulunamadi; otomatik indiriliyor ve kuruluyor (1-3 dakika)...
where winget >nul 2>&1
if not errorlevel 1 (
    winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
)

for /f "delims=" %%P in ('py -3.13 -c "import sys, tkinter; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE goto :python_var
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :python_var
)

echo        winget bulunamadi veya kurulum gecikti; resmi Python 3.13 indiriliyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe' -OutFile (Join-Path $env:TEMP 'py313_setup.exe') -UseBasicParsing"
if exist "%TEMP%\py313_setup.exe" (
    "%TEMP%\py313_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_tcltk=1
    del /f /q "%TEMP%\py313_setup.exe" >nul 2>&1
)

for /f "delims=" %%P in ('py -3.13 -c "import sys, tkinter; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYEXE if exist "%ProgramFiles%\Python313\python.exe" set "PYEXE=%ProgramFiles%\Python313\python.exe"

if not defined PYEXE (
    echo.
    echo  HATA: Python 3.13 otomatik kurulamadi.
    echo  Internet baglantinizi kontrol edip bu dosyayi tekrar calistirin.
    if not "%XMA_KURULUM_TESTI%"=="1" pause
    exit /b 1
)

:python_var
echo        Python hazir: %PYEXE%

rem ---------- [2/6] Google Chrome kontrolu / otomatik kurulum ----------
echo  [2/6] Google Chrome kontrol ediliyor...
set "CHROME_OK="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if not defined CHROME_OK (
    where chrome >nul 2>&1
    if not errorlevel 1 set "CHROME_OK=1"
)
if defined CHROME_OK goto :chrome_ready

echo        Google Chrome bulunamadi; otomatik indiriliyor ve kuruluyor...
where winget >nul 2>&1
if not errorlevel 1 (
    winget install -e --id Google.Chrome --silent --accept-package-agreements --accept-source-agreements
)
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if defined CHROME_OK goto :chrome_ready

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://dl.google.com/chrome/install/latest/chrome_installer.exe' -OutFile (Join-Path $env:TEMP 'chrome_setup.exe') -UseBasicParsing"
if exist "%TEMP%\chrome_setup.exe" (
    "%TEMP%\chrome_setup.exe" /silent /install
    del /f /q "%TEMP%\chrome_setup.exe" >nul 2>&1
)

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_OK=1"
if not defined CHROME_OK (
    echo        UYARI: Chrome otomatik yuklenemedi. Uygulama acilisinda Chrome gerekecektir.
) else (
    echo        Google Chrome kuruldu.
)
goto :after_chrome

:chrome_ready
echo        Google Chrome hazir.

:after_chrome

rem ---------- [3/6] Sanal ortam (.venv) + temel paketler ----------
echo  [3/6] Calisma ortami (.venv) hazirlaniyor...
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1
    if errorlevel 1 rmdir /s /q "%~dp0.venv"
)
if not exist "%~dp0.venv\Scripts\python.exe" (
    "%PYEXE%" -m venv "%~dp0.venv"
)
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo  HATA: Sanal calisma ortami olusturulamadi.
    if not "%XMA_KURULUM_TESTI%"=="1" pause
    exit /b 1
)

echo        Temel paketler indiriliyor ve kuruluyor (internet gerekir)...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" --quiet --disable-pip-version-check

"%~dp0.venv\Scripts\python.exe" -c "import playwright, faster_whisper, sounddevice, numpy, PIL, huggingface_hub, tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  HATA: Gerekli Python paketleri yuklenemedi.
    echo  Internet baglantinizi kontrol edip KUR.bat dosyasini tekrar calistirin.
    if not "%XMA_KURULUM_TESTI%"=="1" pause
    exit /b 1
)
echo        Temel paketler hazir.

rem ---------- [4/6] NVIDIA GPU CUDA kutuphaneleri ----------
echo  [4/6] Ekran karti (GPU) kontrol ediliyor...
set "HAS_NVIDIA="
for /f "delims=" %%G in ('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue).Name -join ';'" 2^>nul') do (
    echo %%G | findstr /i "NVIDIA" >nul && set "HAS_NVIDIA=1"
)
if defined HAS_NVIDIA (
    echo        NVIDIA GPU algilandi; sesle yazma GPU hizlandirmasi kuruluyor...
    "%~dp0.venv\Scripts\python.exe" -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-nvrtc-cu12 --quiet --disable-pip-version-check
) else (
    echo        NVIDIA GPU algilanmadi; sesle yazma CPU modunda hazirlanacak.
)

rem ---------- [5/6] Yerel Turkce STT modeli (onceden indir) ----------
echo  [5/6] Yerel Turkce sesle yazma modeli kontrol ediliyor...
if "%XMA_KURULUM_TESTI%"=="1" (
    echo        Test modu: STT model indirmesi atlandi.
    goto :shortcut
)
if exist "%~dp0stt_models\whisper-large-v3-turbo\model.bin" if exist "%~dp0stt_models\whisper-large-v3-turbo\config.json" goto :stt_cached
echo        Turkce STT modeli indiriliyor ~1.5 GB - yalniz ilk kurulumda...
"%~dp0.venv\Scripts\python.exe" -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='mobiuslabsgmbh/faster-whisper-large-v3-turbo', local_dir=r'%~dp0stt_models\whisper-large-v3-turbo')"
if errorlevel 1 (
    echo        NOT: Model on indirmesi tamamlanamadi; ilk 'Sesle Yaz' kullaniminda otomatik denenecektir.
) else (
    echo        STT modeli basariyla indirildi.
)
goto :shortcut

:stt_cached
echo        STT modeli zaten indirilmis.

:shortcut
rem ---------- [6/6] Masaustu simgesi ----------
echo  [6/6] Masaustu kisayolu olusturuluyor...
if "%XMA_KURULUM_TESTI%"=="1" goto :bitti

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$w=New-Object -ComObject WScript.Shell;" ^
 "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'X-MesajAtma.lnk';" ^
 "$s=$w.CreateShortcut($p);" ^
 "$s.TargetPath='%~dp0BASLAT.bat';" ^
 "$s.WorkingDirectory='%~dp0';" ^
 "$s.IconLocation='%SystemRoot%\System32\shell32.dll,220';" ^
 "$s.Description='X-MesajAtma (X Poster)';" ^
 "$s.Save();" ^
 "Write-Host '        Masaustune X-MesajAtma simgesi eklendi.'" >nul 2>&1

:bitti
echo.
echo  ==========================================================
echo    KURULUM BASARIYLA TAMAMLANDI
echo  ==========================================================
echo.
echo    NASIL KULLANILIR:
echo.
echo    1) Masaustundeki "X-MesajAtma" simgesine cift tiklayin.
echo    2) Ilk acilista Chrome penceresinde X hesabina 1 kez giris yapin.
echo    3) Mesaj yazin, sesle dikte edin veya YZ ile uretip Gonder'e basin!
echo.
echo    Detayli rehber: KULLANIM_KILAVUZU_TR.md / USER_GUIDE_EN.md
echo.
echo  ==========================================================
echo.
if "%XMA_KURULUM_TESTI%"=="1" goto :son
echo  Uygulamayi simdi baslatmak icin herhangi bir tusa basin...
pause >nul
call "%~dp0BASLAT.bat"
:son
endlocal
