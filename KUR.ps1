$ErrorActionPreference = 'Stop'

# X-MesajAtma - tek komutla kurulum
# Kullanim (PowerShell penceresine yapistirin):
#   irm https://raw.githubusercontent.com/karagullemazhar-cpu/X-MesajAtma/main/KUR.ps1 | iex

$repo  = 'karagullemazhar-cpu/X-MesajAtma'
$hedef = Join-Path $env:LOCALAPPDATA 'X-MesajAtma'
$zip   = Join-Path $env:TEMP 'xmesajatma.zip'

Write-Host ''
Write-Host '  X-MesajAtma kuruluyor...' -ForegroundColor Cyan
Write-Host ''

try {
    Invoke-WebRequest -Uri "https://github.com/$repo/archive/refs/heads/main.zip" `
                      -OutFile $zip -UseBasicParsing
} catch {
    Write-Host '  Indirme basarisiz. Internet baglantisini kontrol edin.' -ForegroundColor Red
    Write-Host "  Alternatif: github.com/$repo adresinden Code > Download ZIP"
    Start-Sleep -Seconds 8
    exit 1
}

$gecici = Join-Path $env:TEMP ('xma_' + [guid]::NewGuid().ToString('N'))
Expand-Archive -Path $zip -DestinationPath $gecici -Force
$ic = Get-ChildItem -Path $gecici -Directory | Select-Object -First 1

New-Item -ItemType Directory -Force -Path $hedef | Out-Null
Copy-Item -Path (Join-Path $ic.FullName '*') -Destination $hedef -Recurse -Force
Remove-Item -Path $gecici, $zip -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "  Dosyalar hazir: $hedef"
Write-Host '  Simdi kurulum basliyor...'
Write-Host ''

& (Join-Path $hedef 'KUR.bat')
