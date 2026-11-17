# X Poster — Tam Kullanıcı Kılavuzu (Türkçe)

**X Poster**, kendi X (`x.com`) hesabınız üzerinden ayrı bir Chrome profili (`ChromeProfile/`) kullanarak tek pencereden gönderi paylaşan, yanıt/alıntı/beğeni/repost/yer imi işlemleri yapan, hashtag tarayıp toplu işaretleyen, tamamen yerel Türkçe sesle yazım (**STT**), yerel **WebGPU** veya **Bulut YZ** mesaj üretimi ve **YZ görsel üretimi** sunan Windows masaüstü uygulamasıdır.

> **Not:** İngilizce sürüm için [USER_GUIDE_EN.md](USER_GUIDE_EN.md) dosyasına bakın.

---

## İçindekiler
1. [Ön İhtiyaçlar (Sistem, Yazılım, Donanım ve İzinler)](#1-ön-ihtiyaçlar)
2. [Resim Üretimi (✦ YZ Resim Üret) İçin Gerekli Olanlar](#2-resim-üretimi-i̇çin-gerekli-olanlar)
3. [İlk Kurulum ve Başlatma](#3-i̇lk-kurulum-ve-başlatma)
4. [Tüm Tuşlar ve Kontroller (Ne İşe Yarar / Ne Zaman Çalışır-Çalışmaz)](#4-tüm-tuşlar-ve-kontroller)
5. [Klavye Kısayolları ve Çift Gönderim Koruması](#5-klavye-kısayolları-ve-çift-gönderim-koruması)
6. [Canlı İstatistikler (CounterAPI v2) ve Çevrimdışı Kuyruk](#6-canlı-i̇statistikler-ve-çevrimdışı-kuyruk)
7. [Uygulama Dosyaları ve Saklanan Veriler](#7-uygulama-dosyaları-ve-saklanan-veriler)
8. [Sorun Giderme](#8-sorun-giderme)

---

## 1. Ön İhtiyaçlar

Uygulamanın farklı bölümleri aşağıdaki ön ihtiyaçları kullanır. X gönderimi veya sesle yazım gibi tek tek özellikleri kendi gereksinimi sağlandığında bağımsız olarak kullanabilirsiniz.

### 1.1 Temel Uygulama ve X Paylaşımı İçin (Zorunlu)
| Gereksinim | Detay |
|---|---|
| **İşletim Sistemi** | Windows 10 veya Windows 11. |
| **Python 3.13 + Tkinter** | `baslat.bat` ve `xpost.bat` öncelikle `py -3.13` / `pyw -3.13` arar; yoksa PATH üzerindeki `python` komutunu dener. |
| **Playwright (`playwright`)** | Python 3.13 içinde kurulu olmalıdır. Yalnızca Chrome CDP bağlantısı için kullanılır; `playwright install` ile ek tarayıcı indirilmesi **gerekmez**. |
| **Google Chrome** | Standart yollardan birinde kurulu olmalıdır (`C:\Program Files\Google\Chrome\Application\chrome.exe`, `Program Files (x86)`, `%LocalAppData%\Google\Chrome\Application\chrome.exe` veya PATH). |
| **CDP Port 9222 Boş Olmalı** | Uygulama Chrome'a `127.0.0.1:9222` üzerinden bağlanır. Başka bir otomasyon aracı 9222 portunu kullanmamalıdır. |
| **İlk X Girişi** | Uygulamanın açtığı özel Chrome penceresinde X hesabınıza **1 kez** giriş yapılmalıdır (`ChromeProfile/` klasöründe kalıcı kalır). |
| **İnternet Bağlantısı** | X'e gönderi atma, link işlemleri, Bulut YZ, YZ görsel üretimi ve istatistik gönderimi için gereklidir. |

### 1.2 Yerel Türkçe Sesle Yazım (🎤 Sesle Yaz — Tam Bağımsız STT) İçin
Sesle yazım tarayıcıdan (`turkce-stt-webgpu`) ve Chrome'dan **tamamen bağımsızdır**; doğrudan Python içinden çalışır.
| Gereksinim | Detay |
|---|---|
| **Python Ses/YZ Paketleri** | `faster-whisper`, `ctranslate2`, `sounddevice`, `numpy`. |
| **GPU Hızlandırma (Opsiyonel / Önerilir)** | NVIDIA CUDA uyumlu GPU (ör. RTX serisi) + `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc-cu12`. CUDA GPU bulunamazsa otomatik olarak **CPU (`int8`)** modunda çalışır. |
| **Yerel Model Önbelleği** | İlk çalıştırmada `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (~1.5 GB) `stt_models\whisper-large-v3-turbo\` içine indirilir. Bu dizin mevcutsa tamamen çevrimdışı çalışır. |
| **Mikrofon ve Windows İzni** | Çalışan bir ses giriş aygıtı takılı olmalı ve **Windows Ayarları → Gizlilik ve güvenlik → Mikrofon → "Masaüstü uygulamalarının mikrofonunuza erişmesine izin verin"** seçeneği **Açık** olmalıdır. |

### 1.3 Yapay Zeka Metin Üretimi İçin
- **`✦ WebGPU Mesaj Üret` (Yerel Tarayıcı Modeli):**
  - Çalışan Chrome + **WebGPU destekli GPU** + ilk kullanımda ~1.8 GB model (`gemma-4-E2B-it-q4f16_1-MLC`; açılmazsa sırayla `Qwen3.5-4B-q4f16_1-MLC`, `Qwen3-4B-q4f16_1-MLC` yedeklerine geçer) indirmek için internet (sonraki kullanımlarda `ChromeProfile/` önbelleğinden çevrimdışı çalışabilir).
  - Uygulama içi yerel HTTP sunucusu `127.0.0.1:8765` (doluysa `+20` port aralığındaki ilk boş port) üzerinden `yzmodel/model.html` ve `yzmodel/prompt.json` dosyalarını servis eder.
- **`⚡ Bulut Model Üret`:**
  - Chrome veya GPU gerektirmez.
  - OpenAI uyumlu herhangi bir sağlayıcının (OpenRouter, Groq, OpenAI, yerel Ollama vb.) **Base URL**, **Model** ve **API Key** bilgileri ile ağ erişimi gerekir.

### 1.4 Küçük Görsel Önizleme İçin (Opsiyonel)
- **`Pillow` (`PIL`):** Sağ alt paneldeki görsel önizleme kutusunda seçilen veya üretilen resmi göstermek ve tıklayınca büyük pencereyle açmak için kullanılır (yüklü değilse gönderim yine çalışır, yalnızca önizleme yerine metin gösterilir).

---

## 2. Resim Üretimi İçin Gerekli Olanlar

`✦ YZ Resim Üret` butonunun sorunsuz çalışması için **dört ön koşulun aynı anda** sağlanması gerekir:

1. **`Resim Ekle` kutucuğu işaretli olmalıdır:** İşaretsizse `Dosya Seç...`, `✦ YZ Resim Üret` ve `✕` butonları devre dışıdır (`disabled`).
2. **Geçerli bir OpenRouter API Key girilmiş olmalıdır:**
   - Sağ paneldeki **Bulut Model** bölümünün **`API Key`** kutusuna OpenRouter anahtarınızı girin.
   - Uygulama görsel üretimini sabit olarak OpenRouter görsel uç noktası (`https://openrouter.ai/api/v1/images`) ve **`recraft/recraft-v4.1-flash-v2:free`** modeli üzerinden yapar.
   - **Önemli not:** Bulut Model alanında `Base URL` olarak Groq veya başka bir OpenAI sağlayıcısı yazılı olsa bile `✦ YZ Resim Üret` doğrudan OpenRouter API anahtarına ihtiyaç duyar (anahtar geçerli OpenRouter anahtarı değilse OpenRouter yetkilendirme hatası döner).
3. **`Ne paylaşmak istersin?` (mesaj kutusu) dolu olmalıdır:**
   - Mesaj kutusu boşsa görsel üretilmez ve uygulama önce mesaj yazmanızı/üretmenizi ister.
4. **Aktif İnternet Bağlantısı olmalıdır:**
   - İlk aşamada Türkçe mesajınız İngilizce görsel sahneye ve kısa Türkçe afiş sloganına dönüştürülür (önce Bulut Model alanındaki URL+Model denenir; yoksa/başarısız olursa OpenRouter ücretsiz metin modelleri `baidu/ernie-5.5-flash-preview:free` → `inclusionai/ling-3.2-flash:free` denenir; onlar da yanıt vermezse yerel kural tabanlı Türkçe sloganlı yedek istem kullanılır).
   - İkinci aşamada `9:16` veya `16:9` oranında görsel üretilip `generated_images\` klasörüne kaydedilir, `Resim Ekle` otomatik aktif kalır ve görsel gönderime hazırlanır.

> **Dosya boyutu sınırı:** İster kendi bilgisayarınızdan seçin ister YZ ile üretin, X medya sınırı nedeniyle `4.8 MB` (`4_800_000` bayt) üzeri görsellerde uyarı verilir; seçilen/üretilen gerçek resim `state.json` içinde saklanır.

---

## 3. İlk Kurulum ve Başlatma

1. Normal kullanım için **`baslat.bat`** dosyasına çift tıklayın (konsol penceresi açmadan `pyw -3.13 xpost.py` başlatır). Hata/tanı çıktılarını terminalde görmek isterseniz **`xpost.bat`** kullanın.
2. Uygulama kendi Chrome profilini (`ChromeProfile/`) açar. Sağ üstteki durum etiketi `● X Girişi Gerekli` gösteriyorsa açılan Chrome penceresinde X hesabınıza giriş yapın.
3. Giriş tamamlandığında durum otomatik olarak `● Chrome Bağlı` ve alt durum çubuğu `Hazır ✓` hâline gelir. (Tek seferliktir; sonraki açılışlarda oturum açık kalır.)

---

## 4. Tüm Tuşlar ve Kontroller

### 4.1 Üst Başlık (Header)

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **`X-UY (≤ 280 krk)`** | AI ile mesaj üretirken toplam karakter hedefini (`mesaj + hashtag ≤ 280`) belirler. | Her zaman değiştirilebilir; sonraki **WebGPU** ve **Bulut** üretimlerini etkiler. | Kullanıcının kutuya elle 280 karakterden uzun yazmasını veya **Gönder**'e basmasını engellemez. |
| **`🌙 Koyu` / `☀️ Açık`** | Açık ve koyu tema arasında geçiş yapar, tercihi `state.json`'a kaydeder. | Her zaman çalışır. | — |
| **`● Chrome Bağlı` / `● Giriş Gerekli`** | Chrome ve X oturum bağlantı durumunu gösterir. | Otomatik güncellenir. | Tıklanabilir bir buton değildir. |

### 4.2 Sol Üst Kart: Mesaj Kutusu ve Sesle Yazım (STT)

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **Mesaj Kutusu** (`Ne paylaşmak istersin?`) | Gönderilecek ana metni yazar/düzenlersiniz (`Ctrl+Enter` gönderir). `280` karakteri aşan bölüm kırmızı vurgulanır. | Her zaman yazılabilir/yapıştırılabilir. | Gönderimi tek başına bloklamaz; ancak X hesabınız uzun gönderiye kapalıysa paylaşım X tarafından reddedilir. |
| **`Temizle`** | Mesaj kutusundaki tüm metni temizler. | Her zaman çalışır. | — |
| **`0/280` Sayaç + Halka** | Mesaj + hashtag birleşik uzunluğunu gösterir. | Her tuşta ve yapıştırmada güncellenir. | Bilgi göstergesidir (tıklanmaz). |
| **`🎤 Sesle Yaz`** (`idle`) | Sesle yazımı başlatır. İlk seferde uygulama içi **Mikrofon İzni** penceresini açar; onaydan sonra GPU/CPU modelini yükleyip mikrofonu dinler ve konuşulanları kutuya canlı yazar. | Her açılışta önce izin modalından onay verilince çalışır (`_stt_perm_granted` başlangıçta sıfırlıdır). Mikrofon ve STT paketleri gerekir. | İzin penceresinde **İptal** seçilirse veya sistemde kullanılabilir mikrofon yoksa başlamaz. |
| **`⏳ Hazırlanıyor (İptal)`** (`loading`) | Model/akış yüklenirken aynı butona tekrar basarak yüklemeyi **anında iptal eder**. | Yalnızca yükleme aşamasında aktiftir. | İptalden hemen sonra tek tıkla tekrar başlatılabilir. |
| **`⏹ Dinliyor (Durdur)`** (`listening`) | Mikrofonu kapatır ve son cümleyi yazıya döküp (`⏳ Yazılıyor...`) oturumu bitirir. | Dinleme aktifken çalışır. | Son cümle işlenirken tekrar basılırsa zorla sıfırlanır. |
| **Hassasiyet Menüsü (`Sessiz` / `Normal` / `Gürültülü`)** | Mikrofon eşik hassasiyetini ortam sesine göre ayarlar (`state.json`'a kaydedilir). | Her zaman çalışır (boştayken ve dinleme sırasında canlı etki eder). | Ses çok düşükse `Sessiz`, çok kalabalık ortamdaysa `Gürültülü` seçilmelidir. |
| **Ses Seviye Çubuğu** | Mikrofondan gelen canlı ses düzeyini ve kırmızı konuşma eşiğini gösterir. **Mavi** = ses var ama eşik altı, **Yeşil** = konuşma algılandı ve yazıya dökülüyor. | `Dinliyor` / `Yazılıyor` durumlarında hareket eder. | 3.5 sn hiç veri gelmezse `⚠ Ses gelmiyor` uyarısı çıkar (Windows mikrofon izni veya cihaz seçimi kontrol edilmelidir). |
| **`🎙 Mikrofon:` Seçici** | Kullanılacak Windows ses giriş cihazını her zaman ekrandan seçmenizi sağlar. | **Her zaman çalışır:** boştayken bir sonraki oturumu seçer; **dinleme sırasındayken değiştirilirse eski akışı kapatıp yeni seçilen cihazla anında yeniden başlatır**. | Listede mikrofon yoksa seçim yapılamaz. |
| **`↻ Yenile`** | Windows'ta yeni takılan/çıkarılan USB veya Bluetooth mikrofonları tekrar tarar. | Her zaman çalışır. | Mikrofon cihazları dinamik olarak değişmediyse liste aynı kalır. |

### 4.3 Sol Orta ve Alt Kartlar: Hashtag'ler ve Konu

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **Hashtag'ler Kutusu** | Altına eklenecek hashtag (`#...`), bahsetme (`@...`) veya sabit metni tutar (`hashtags.txt`'e anında kaydedilir). | Her zaman düzenlenebilir. | Metnin başına otomatik `#` eklemez. Ancak sağ alttaki **Hashtag İşaretleme** yalnızca `#` ile başlayan kelimeleri listeler. |
| **Konu Kutusu** | **WebGPU** ve **Bulut** metin üretiminin odaklanacağı konu metni (`state.json`'a kaydedilir). | Her zaman düzenlenebilir. | Boş bırakılırsa `✦ WebGPU Mesaj Üret` ve `⚡ Bulut Model Üret` tuşları çalışmaz. |

### 4.4 Sağ Üst Kart: Yapay Zeka Mesaj Üretimi

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **`Çeşitlilik` Kaydıracı (`0.3–1.3`)** | Üretim sıcaklığını (`temperature`) ayarlar (`state.json`'a kaydedilir). | Her zaman çalışır. | — |
| **`✦ WebGPU Mesaj Üret`** | Chrome içinde yerel WebGPU modeliyle 7 farklı açıdan birini seçerek Türkçe mesaj üretir (`yzmodel/prompt.json` kullanır); mesaj kutusunu günceller. | **Konu** doluysa, aktif üretim sürmüyorsa (`!gen_busy`) ve Chrome/WebGPU çalışıyorsa. | Konu boşsa uyarı verir; üretim sürerken (`gen_busy`) devre dışıdır; donanım WebGPU desteklemiyorsa hata verir. |
| **`⚡ Bulut Model Üret`** | OpenAI uyumlu API üzerinden mesaj üretir. `X-UY` kapalıysa kısa çıktıyı odak noktasıyla 5–7 cümleye genişletebilir. | **Konu**, **Base URL**, **Model** ve **API Key** alanlarının **hepsi** doluysa ve aktif üretim yoksa (`!gen_busy`). | Bu 4 alandan biri boşsa uyarı verip çalışmaz; üretim sırasında devre dışıdır. |
| **`Base URL` / `Model` / `API Key`** | Bulut sağlayıcı bağlantı alanları (`API Key` maskeli gösterilir; tümü `state.json`'da saklanır). | Her zaman düzenlenebilir. | Bulut üretimi ve (`API Key` özelinde) `✦ YZ Resim Üret` için doldurulmalıdır. |

### 4.5 Sağ Orta Kart: İşlemler & Medya

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **`Yeni Gönderi`** | İşaretliyse mesaj kutusu (+ hashtag) ve/veya görseli yeni gönderi olarak paylaşır. | Her zaman açılıp kapatılabilir. | Kutu ve görsel ikisi de boşsa `Yeni Gönderi` tek başına `Gönder ↗` butonunu açmaz. |
| **`Link:` + Link Kutusu** | İşaretlendiğinde alttaki link kutusu ve 5 işlem çipini aktif eder. | Her zaman açılıp kapatılabilir. | İşaretsizken link kutusu ve 5 işlem çipi (`Reply`, `Quote`, `Like`, `Repost`, `Bookmark`) **devre dışıdır**. |
| **`Reply`** | Verilen linkteki gönderiye mesaj + hashtag (+ görsel) ile yanıt atar. | `Link:` işaretliyken aktiftir; geçerli `/status/<ID>` linki VE mesaj veya görsel gerektirir. | `Link:` işaretsizse devre dışıdır; mesaj ve görsel ikisi de boşsa hata verir. |
| **`Quote`** | Verilen linkteki gönderiyi mesaj + hashtag (+ görsel) ile alıntılar. | `Link:` işaretliyken aktiftir; geçerli `/status/<ID>` linki VE mesaj veya görsel gerektirir. | `Link:` işaretsizse devre dışıdır; mesaj ve görsel ikisi de boşsa hata verir. |
| **`Like`** | Linkteki gönderiyi beğenir (zaten beğenilmişse atlar). | `Link:` işaretliyken ve geçerli `/status/<ID>` linki varken (mesaj boş olsa da çalışır). | `Link:` işaretsizse devre dışıdır. |
| **`Repost`** | Linkteki gönderiyi yeniden paylaşır (zaten yapılmışsa atlar). | `Link:` işaretliyken ve geçerli `/status/<ID>` linki varken. | `Link:` işaretsizse devre dışıdır. |
| **`Bookmark`** | Linkteki gönderiyi yer imlerine ekler (zaten ekliyse atlar). | `Link:` işaretliyken ve geçerli `/status/<ID>` linki varken. | `Link:` işaretsizse devre dışıdır. |
| **`Resim Ekle`** | Seçili/üretili görseli yeni gönderi, Reply ve Quote içeriklerine iliştirir. | Her zaman açılıp kapatılabilir. | İşaretsizken görsel butonları (`Dosya Seç...`, `✦ YZ Resim Üret`, `✕`) kilitlenir ve gönderime görsel konmaz. |
| **`Dosya Seç...`** | Bilgisayardan `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` dosyası seçer. | `Resim Ekle` işaretliyken ve görsel üretimi sürmüyorken (`!img_busy`). | `Resim Ekle` kapalıysa veya görsel üretimi sürerken devre dışıdır. |
| **`✦ YZ Resim Üret`** | Mesaj kutusundaki metinden OpenRouter + Recraft ile görsel üretir. | `Resim Ekle` işaretliyken, `!img_busy` iken, **Bulut `API Key` dolu** VE **mesaj kutusu dolu** ise. | `Resim Ekle` işaretsizse kilitlidir; `API Key` veya mesaj boşsa uyarı verir ve çalışmaz. |
| **`✕` (Görsel Temizle)** | Seçili görseli temizler ve açık önizleme penceresini kapatır. | `Resim Ekle` işaretliyken, `!img_busy` iken ve geçerli görsel seçiliyken. | Görsel seçili değilken veya `Resim Ekle` kapalıyken devre dışıdır. |
| **Küçük Önizleme Kutusu** | Görsele tıklandığında tam boyut önizleme penceresi açar (`Esc` ile kapanır). | Geçerli bir görsel yüklü ise. | Görsel yoksa veya dosya bulunamadıysa tepki vermez. |

### 4.6 Sağ Alt Kart: Hashtag İşaretleme (30+ Mesaj)

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **Hashtag Satırındaki `Like` / `Repost`** | O etiket aramasında hangi işlemlerin yapılacağını seçer (`state.json`'a kaydedilir). | `Hashtag'ler` kutusunda `#` ile başlayan kelime varsa listelenir. | Kutuda `#etiket` yoksa satır oluşmaz. |
| **`İşaretle`** | X aramasında ilgili `#etiket` sekmesini açar, sanal kaydırma yaparak **en az 30 mesajı** seçili `Like`/`Repost` ile işaretler. | Başka gönderim/işaretleme yokken (`!busy`) ve o satırda `Like` veya `Repost`'tan en az biri seçiliyken (X girişi yapılmış olmalı). | `busy` durumundayken devre dışıdır; `Like` ve `Repost` ikisi de seçili değilse uyarı verir ve çalışmaz. |

### 4.7 Alt Sabit Çubuk

| Öğe | Görevi | Ne Zaman Çalışır | Ne Zaman Çalışmaz / Kısıtlar |
|---|---|---|---|
| **`Gönder ↗`** | Planlanan işleri sırayla uygular (önce `Yeni Gönderi`, ardından link işlemleri `Like → Bookmark → Repost → Reply → Quote`). | Başka işlem yokken (`!busy`) ve en az 1 hazır iş varsa (`Yeni Gönderi`+metin/görsel VEYA `Link:`+link+en az 1 çip). | Aktif işlem yokken kilitlidir (`disabled`); `busy` iken `Gönderiliyor...` olarak kilitlenir; `Link:` işaretli olup link veya çip yoksa uyarı verir; X girişi yoksa Chrome'da giriş ister. |
| **`x: @mkaragulle71` / `YouTube: @MixedMixedInfo`** | Yazar X mesaj ekranını veya YouTube kanalını Chrome'da açar. | Her zaman çalışır (1.5 saniye çift tıklama korumalıdır). | Chrome bulunamazsa varsayılan tarayıcıya/hata durumuna düşer. |

---

## 5. Klavye Kısayolları ve Çift Gönderim Koruması

- **`Ctrl + Enter`** *(Mesaj Kutusu içindeyken):* `Gönder ↗` ile aynı gönderimi tetikler (`on_send`).
- **`Enter` / `Esc`** *(Mikrofon İzin penceresinde):* `Enter` = `İzin Ver ve Başlat`, `Esc` = `İptal`.
- **`Esc`** *(Büyük Görsel Önizleme penceresinde):* Önizleme penceresini kapatır.
- **90 Saniye Çift Gönderim Koruması:** Aynı metin + aynı görsel 90 saniye içinde tekrar gönderilmeye çalışılırsa ilk tıklamada uyarı verir (`⚠ Bu mesaj az önce gönderildi...`). Gerçekten tekrar göndermek isterseniz **ikinci kez** `Gönder ↗` (veya `Ctrl+Enter`) yapmanız gerekir.

---

## 6. Canlı İstatistikler ve Çevrimdışı Kuyruk

Uygulama aşağıdaki üç CounterAPI v2 sayacını canlı olarak günceller:
1. **`atilan-mesaj-adedi`:** Uygulama üzerinden başarıyla yayınlanan her yeni gönderi, yanıt (`Reply`) ve alıntı (`Quote`) için `+1` *(Like, Repost, Bookmark ve Hashtag işaretlemeleri sayılmaz; başarısız olan gönderimler sayılmaz)*.
2. **`webgpu-adedi`:** `✦ WebGPU Mesaj Üret` veya `⚡ Bulut Model Üret` ile başarıyla üretilen her mesaj için `+1`.
3. **`uretilen-resim`:** `✦ YZ Resim Üret` ile başarıyla üretilen her resim için `+1`.

**Çevrimdışı ve kapanış dayanıklılığı:**
- Olay gerçekleştiğinde sayı önce güvenli biçimde [pending_stats.json](pending_stats.json) içine kaydedilir ve arka planda canlı gönderilir; her başarılı tekil artışta dosya güncellenir.
- İnternet veya API erişim hatası olursa kalan veriler diskte kalır, uygulama açıkken arka plan zamanlayıcısı bağlantıyı periyodik olarak tekrar dener; uygulama kapatılıp yeniden açıldığında da bekleyen tüm artışlar ilk erişimde otomatik gönderilip dosya temizlenir.

---

## 7. Uygulama Dosyaları ve Saklanan Veriler

| Dosya / Klasör | Açıklama |
|---|---|
| `baslat.bat` / `xpost.bat` | Başlatma kısayolları (konsolsuz / konsollu). |
| `xpost.py` | Ana uygulama, arayüz, X otomasyonu, bulut/görsel istemcisi ve CounterAPI kuyruğu. |
| `xpost_stt.py` | Tarayıcıdan tamamen bağımsız yerel Türkçe STT (`sounddevice` + VAD + `faster-whisper`) modülü. |
| `yzmodel/model.html`, `yzmodel/prompt.json` | Yerel WebGPU metin modeli sayfası ve ortak Türkçe prompt şablonları. |
| `stt_models/whisper-large-v3-turbo/` | Yerel önbelleğe alınan Türkçe ses tanıma modeli. |
| `generated_images/` | `✦ YZ Resim Üret` ile üretilen `.png/.webp/.jpg` görselleri. |
| `ChromeProfile/` | Uygulamaya özel X oturum profili (kimseyle paylaşmayın, silmeyin). |
| `hashtags.txt` | Hashtag kutusu içeriği. |
| `state.json` / `state.json.bak` | Uygulama ayarları, konu, bulut URL/API Key/Model, görsel yolu, tema ve bölme konumları. |
| `pending_stats.json` | Ağ erişimi kesildiğinde veya erken kapanışta sırada bekleyen CounterAPI istatistikleri (tamamlanınca otomatik silinir). |

---

## 8. Sorun Giderme

- **Ses seviye çubuğu mavi oynuyor ama kutuya yazı gelmiyor:** Mikrofon ses düzeyi çok kısık veya ortam gürültülü olabilir. Çubuktaki kırmızı çizgiyi geçince renk **yeşile** dönmelidir. Konuşurken yeşil olmuyorsa hassasiyet menüsünden **`Sessiz`** seçeneğini deneyin veya Windows ses ayarlarından mikrofon düzeyini/kazancını yükseltin, ya da alttaki `🎙 Mikrofon:` menüsünden başka bir aygıt (ör. `WASAPI` / `DirectSound`) seçin.
- **`Mikrofon açılamadı` / `⚠ Ses gelmiyor` uyarısı:** Windows Ayarları → Gizlilik ve güvenlik → Mikrofon altında masaüstü uygulamalarına izin verildiğini doğrulayın; başka bir ses aygıtı seçip `↻ Yenile` butonuna basın.
- **`Chrome bulunamadı` hatası:** Chrome kurulu yolunuzu `xpost.py` içindeki `CHROME_CANDIDATES` listesine ekleyin.
- **WebGPU veya port çakışması (`9222`):** Aynı profille açık kalmış Chrome penceresi varsa kapatın; 9222 portu başka program tarafından kullanılıyorsa `xpost.py` içindeki `CDP_PORT` değerini değiştirin.
- **Resim üretimi hata veriyor:** `Resim Ekle`'nin işaretli, mesaj kutusunun dolu, internetin aktif ve Bulut `API Key` alanında geçerli bir **OpenRouter API Key** bulunduğundan emin olun.
