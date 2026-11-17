# X-MesajAtma

Kullanicilardan gelen mesajlari sayan ve **canli** gosteren kucuk bir panel.

Bilgisayarina kurulur, tarayicida acilir, 4 sayiyi canli gosterir:

| Sayi | Ne demek |
|---|---|
| **Toplam mesaj** | Simdiye kadar gelen tum mesajlar |
| **Bugun** | Bugun gelen mesajlar (son 1 saat de altinda yazar) |
| **Kac kisi yazdi** | Kac farkli kullanici |
| **Kisi basina** | Kullanici basina ortalama mesaj |

Ekranda ayrica **kim kac mesaj atmış** listesi ve **son mesajlar** canli akisi var.

- Web sitesi gerekmez. Sunucu kiralamak gerekmez. API anahtari gerekmez.
- Veriler senin bilgisayarinda kalir (`mesajlar.db` dosyasi).
- Tek komutla kurulur, tek tikla calisir.

---

## Kurulum - Windows (en kolay yol)

> Bilgisayar bilgisi gerekmez. Yazilanlari sirayla yap.

**1. Indir**

Bu sayfanin sag ustundeki yesil **`Code`** dugmesine bas → **`Download ZIP`** sec.
Inen dosyayi **sag tik → Tumunu ayikla (Extract All)** ile cikart.

**2. Kur**

Cikarttigin klasorde **`KUR.bat`** dosyasina **cift tikla**.

Siyah bir pencere acilir ve her seyi kendisi yapar:
Python yoksa kurar, gerekli paketleri indirir, masaustune simge ekler.
Bu islem 1-5 dakika surer. **Pencere kapanana kadar bekle.**

**3. Calistir**

Masaustunde olusan **`X-MesajAtma`** simgesine **cift tikla**.

Tarayici kendiliginden acilir ve panel gorunur:
**http://127.0.0.1:5077**

Kapatmak icin acilan siyah pencereyi kapat. Bu kadar.

---

## Kurulum - tek komut (PowerShell)

Baslat menusune `PowerShell` yaz, acilinca bu satiri yapistir ve Enter'a bas:

```powershell
irm https://raw.githubusercontent.com/karagullemazhar-cpu/X-MesajAtma/main/KUR.ps1 | iex
```

Geri kalan her seyi kendisi yapar.

---

## Nasil calistirilir (kurulumdan sonra)

Her gun yapman gereken tek sey:

1. Masaustundeki **`X-MesajAtma`** simgesine cift tikla.
2. Tarayicida panel acilir: `http://127.0.0.1:5077`
3. Bitince siyah pencereyi kapat (panel kapanir).

Panel kendini **2 saniyede bir** yeniler; sayfayi elle yenilemene gerek yok.

Istersen paneldeki **"Test mesaji gonder"** dugmesine bas: sayilarin nasil arttigini gorursun.

---

## Kendi uygulamana baglama

Uygulaman bir mesaj aldiginda (veya gonderdiginde) tek bir adrese haber vermesi yeterli.
**3 yol var, en kolayi en basta:**

### 1. Tarayici / webhook (kod yazmadan)

```
http://127.0.0.1:5077/api/mesaj?kullanici=ali&mesaj=merhaba
```

Bu adresi tarayiciya yazinca da calisir. IFTTT, Zapier, Make gibi araclarda
"webhook" alanina bu adresi yazabilirsin.

### 2. Herhangi bir dilden HTTP istegi (POST)

```
POST http://127.0.0.1:5077/api/mesaj
Content-Type: application/json

{"kullanici": "ali", "mesaj": "merhaba", "kanal": "uygulama"}
```

### 3. Python

```python
import requests
requests.post("http://127.0.0.1:5077/api/mesaj",
              json={"kullanici": "ali", "mesaj": "merhaba"}, timeout=5)
```

Hazir ornek dosya: `ornek_gonder.py`

```bash
python ornek_gonder.py 20
```

### Alanlar

| Alan | Zorunlu | Aciklama |
|---|---|---|
| `kullanici` | **evet** | Kim yazdi (ornek: `ali`, `kullanici_123`) |
| `mesaj` | hayir | Mesajin kendisi |
| `kanal` | hayir | Nereden geldi (ornek: `whatsapp`, `uygulama`) |

Ayni `kullanici` degerini kullanan mesajlar tek kisi sayilir.

---

## Telefondan izleme

Varsayilan olarak panel **sadece kendi bilgisayarinda** acilir. Bu guvenli olandir.

Ayni Wi-Fi'deki telefondan izlemek istersen:

1. Klasordeki `.env.example` dosyasini kopyala, adini `.env` yap.
2. Icine sunlari yaz:
   ```
   HOST=0.0.0.0
   MESAJ_ANAHTARI=kendine-bir-kelime-sec
   ```
3. `BASLAT.bat` ile yeniden baslat.
4. Bilgisayarin yerel IP'sini ogren (`ipconfig` → IPv4 Adresi), telefonda
   `http://O-IP:5077` yaz.

`MESAJ_ANAHTARI` yazarsan panel sifre ister; adresin sonuna `?anahtar=kelimen`
ekleyerek acarsin.

---

## Sık sorunlar

| Sorun | Cozum |
|---|---|
| `KUR.bat` acilip hemen kapaniyor | Python kurulu degil. Kurulum penceresi python.org sayfasini acar; Python'u kurarken **"Add python.exe to PATH"** kutusunu isaretle, sonra `KUR.bat`'a tekrar cift tikla. |
| "Windows protected your PC" uyarisi | **More info** → **Run anyway**. Dosya sana ait. |
| Panel acilmiyor | Siyah pencerede hata var mi bak. Port doluysa `.env` icinde `PORT=5078` yaz ve tekrar baslat. |
| Sayilar artmiyor | Uygulaman `http://127.0.0.1:5077/api/mesaj` adresine istek atiyor mu kontrol et. Paneldeki "Test mesaji gonder" ile deneyebilirsin. |
| Antivirus uyarisi | `KUR.bat` sadece Python kurar ve paket indirir; `.bat` dosyalari antiviruslere zaman zaman supheli gorunur. Izin ver. |

---

## Gizli bilgiler (API anahtari) kurali

Bu projede **hicbir API anahtari yok** ve olmayacak.

Kendi anahtarlarini eklersen:

- Anahtari **asla** `app.py` gibi dosyalara yazma.
- `.env` dosyasina yaz. `.env` zaten `.gitignore` icinde, GitHub'a gitmez.
- `.env` dosyasini kimseyle paylasma, ekran goruntusunu alma.

---

## macOS / Linux

```bash
git clone https://github.com/karagullemazhar-cpu/X-MesajAtma.git
cd X-MesajAtma
bash kur.sh
./baslat.sh
```

---

## Dosyalar

| Dosya | Ne ise yarar |
|---|---|
| `app.py` | Uygulamanin kendisi (panel + API + veritabani) |
| `KUR.bat` / `kur.sh` | Kurulum |
| `BASLAT.bat` / `baslat.sh` | Calistirma |
| `KUR.ps1` | Tek komutla uzaktan kurulum |
| `ornek_gonder.py` | Ornek mesaj gonderme |
| `mesajlar.db` | Veriler (kurulumdan sonra olusur, GitHub'a gitmez) |
| `.env` | Gizli ayarlar (istege bagli, GitHub'a gitmez) |

---

## Lisans

MIT - diledigin gibi kullan, degistir, paylas.
