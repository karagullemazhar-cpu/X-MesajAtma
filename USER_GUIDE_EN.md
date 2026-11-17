# X Poster — Complete User Guide (English)

**X Poster** is a Windows desktop application that posts to your X (`x.com`) account via a dedicated Chrome profile (`ChromeProfile/`). From a single-page interface (Light & Dark themes), it supports composing new posts, reply/quote/like/repost/bookmark link actions, batch hashtag marking (30+ posts), standalone local Turkish Speech-to-Text (**STT**), local **WebGPU** or **Cloud AI** text generation, **AI image generation**, and resilient **CounterAPI v2** telemetry.

> **Note:** For the Turkish user guide, see [KULLANIM_KILAVUZU_TR.md](KULLANIM_KILAVUZU_TR.md).

---

## Table of Contents
1. [Prerequisites (OS, Software, Hardware & Permissions)](#1-prerequisites)
2. [Requirements for AI Image Generation (✦ YZ Resim Üret)](#2-requirements-for-ai-image-generation)
3. [First-Time Setup & Launching](#3-first-time-setup--launching)
4. [All Buttons & Controls (Purpose, When They Work / Don't Work)](#4-all-buttons--controls)
5. [Keyboard Shortcuts & Double-Send Protection](#5-keyboard-shortcuts--double-send-protection)
6. [Live Statistics (CounterAPI v2) & Offline Queue](#6-live-statistics-and-offline-queue)
7. [Project Files & Stored Data](#7-project-files-and-stored-data)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

Different capabilities in X Poster have independent prerequisites, so features whose requirements are met work on their own.

### 1.1 Core App & Posting to X (Required)
| Requirement | Details |
|---|---|
| **Operating System** | Windows 10 or Windows 11. |
| **Python 3.13 + Tkinter** | `baslat.bat` and `xpost.bat` prioritize `py -3.13` / `pyw -3.13`, falling back to `python` on `PATH`. |
| **Playwright (`playwright`)** | Installed in Python 3.13. Used solely for Chrome CDP control — downloading Playwright browsers is **not** needed. |
| **Google Chrome** | Installed in standard Windows locations (`C:\Program Files\Google\Chrome\Application\chrome.exe`, `Program Files (x86)`, `%LocalAppData%\Google\Chrome\Application\chrome.exe`, or `PATH`). |
| **CDP Port 9222 Free** | Connects to Chrome at `127.0.0.1:9222`. No other automation tool should occupy port `9222`. |
| **One-Time X Login** | Sign in to your X account **once** inside the dedicated Chrome window opened by the app (persisted in `ChromeProfile/`). |
| **Internet Connection** | Required for posting to X, link actions, hashtag marking, Cloud AI generation, AI image generation, and CounterAPI telemetry. |

### 1.2 Standalone Turkish Voice Dictation (🎤 Sesle Yaz — Local STT)
Voice dictation is **100% independent** from Chrome and `turkce-stt-webgpu`, running directly inside Python.
| Requirement | Details |
|---|---|
| **Python Audio/AI Packages** | `faster-whisper`, `ctranslate2`, `sounddevice`, `numpy`. |
| **GPU Acceleration (Optional / Recommended)** | CUDA-capable NVIDIA GPU + `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc-cu12`. Falls back seamlessly to **CPU (`int8`)** if no CUDA GPU is available. |
| **Local Model Cache** | Downloads `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (~1.5 GB) into `stt_models\whisper-large-v3-turbo\` on first use; runs fully offline once cached. |
| **Microphone & Windows Permission** | A working microphone input device + **Windows Settings → Privacy & security → Microphone → "Let desktop apps access your microphone"** enabled. |

### 1.3 AI Message Generation
- **`✦ WebGPU Mesaj Üret` (Local Browser LLM):**
  - Requires Google Chrome + a **WebGPU-capable GPU** + internet on the very first run to download `gemma-4-E2B-it-q4f16_1-MLC` (~1.8 GB, stored in Chrome cache; falls back to `Qwen3.5-4B-q4f16_1-MLC` or `Qwen3-4B-q4f16_1-MLC` on failure).
  - Served locally from `yzmodel/model.html` & `yzmodel/prompt.json` on `127.0.0.1:8765` (or the next free port within `+20`).
- **`⚡ Bulut Model Üret` (Cloud LLM):**
  - Requires **neither Chrome nor GPU**.
  - Requires **Base URL**, **Model**, and **API Key** for any OpenAI-compatible endpoint (OpenRouter, Groq, OpenAI, local Ollama, etc.) plus network access.

### 1.4 Thumbnail & Full-Size Image Preview (Optional)
- **`Pillow` (`PIL`):** Enables image thumbnail rendering and clicking the thumbnail to open a full-size preview window. (Posting and generation still work even without `Pillow`.)

---

## 2. Requirements for AI Image Generation

All **four** prerequisites below must be met for **`✦ YZ Resim Üret`** to run:

1. **`Resim Ekle` (Attach Image) must be checked:** When unchecked, `Dosya Seç...`, `✦ YZ Resim Üret`, and `✕` are all disabled.
2. **A valid OpenRouter API Key must be entered:**
   - Paste your OpenRouter API key into the **`API Key`** field inside the **Bulut Model** panel.
   - Image generation always calls OpenRouter's images endpoint (`https://openrouter.ai/api/v1/images`) using model **`recraft/recraft-v4.1-flash-v2:free`**.
   - **Important:** Even if your Cloud LLM `Base URL` points to another provider (such as Groq) for text, **`✦ YZ Resim Üret` still requires an OpenRouter API Key** (otherwise OpenRouter rejects authentication).
3. **The message box (`Ne paylaşmak istersin?`) must not be empty:**
   - The app first translates/distills your Turkish post into a visual scene prompt and a short uppercase Turkish headline/slogan. If the message box is empty, image generation refuses to run and prompts you to enter/generate text first.
4. **Active Internet Connection:**
   - Step 1 builds an English visual prompt (tries your Cloud Model first, then free OpenRouter text fallbacks `baidu/ernie-5.5-flash-preview:free` → `inclusionai/ling-3.2-flash:free`, or a local Turkish-slogan fallback if offline/rate-limited on text translation).
   - Step 2 generates a `9:16` or `16:9` poster via `recraft/recraft-v4.1-flash-v2:free`, saves it to `generated_images\`, keeps `Resim Ekle` checked, and updates the preview.

> **File size limit:** X limits image uploads to ~`4.8 MB` (`4_800_000` bytes). Selecting larger files triggers a warning in the status bar.

---

## 3. First-Time Setup & Launching

1. Double-click **`baslat.bat`** for normal console-free launch (`pyw -3.13 xpost.py`), or **`xpost.bat`** to see terminal diagnostics.
2. The app launches a dedicated Chrome window (`ChromeProfile/`). If the top-right status pill displays **`● X Girişi Gerekli`**, sign in to X inside that Chrome window.
3. Once logged in, the pill updates to **`● Chrome Bağlı`** and the bottom status reads **`Hazır ✓`**. Your X session persists across restarts.

---

## 4. All Buttons & Controls

### 4.1 Top Header Bar

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **`X-UY (≤ 280 krk)`** | Targets `message + hashtags ≤ 280` chars during **WebGPU** / **Cloud** generation; unchecking allows long mode (up to `800` chars). | Toggable anytime; affects subsequent AI generation. | Does **not** block typing or sending longer posts manually (X decides whether Premium long-posts are allowed). |
| **`🌙 Koyu` / `☀️ Açık`** | Switches between Light and Dark themes immediately and persists to `state.json`. | Always enabled. | — |
| **Connection Pill** (`● Chrome Bağlı`, etc.) | Read-only Chrome/X login status badge. | Updates automatically. | Not interactive. |

### 4.2 Left Column — Card 1: Message Box & Native STT

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **Message Box** (`Ne paylaşmak istersin?`) | Main tweet/reply/quote editor (`Ctrl+Enter` sends). Text past `280` combined chars highlights in red. | Always editable. | Highlighting is advisory; X itself rejects over-limit tweets on non-Premium accounts. |
| **`Temizle`** | Clears the entire message box. | Always enabled. | — |
| **`0/280` Counter + Progress Ring** | Live combined length of `message + hashtags`. | Updates on every keystroke/paste. | Read-only indicator. |
| **`🎤 Sesle Yaz`** (`idle`) | Starts voice dictation. On first click per session, opens an **in-app Microphone Permission modal**; after approval, loads `faster-whisper` and streams speech live into the box. | Requires confirmation in the modal (`_stt_perm_granted` resets to `False` on every fresh launch), a mic device, and Windows desktop mic access. | Stays idle if you click **İptal** or no input device exists. |
| **`⏳ Hazırlanıyor (İptal)`** (`loading`) | Aborts model/stream initialization immediately and returns to `idle`. | Active only while loading. | Resets cleanly so you can immediately click again to retry. |
| **`⏹ Dinliyor (Durdur)`** (`listening`) | Stops mic capture and flushes remaining audio (`⏳ Yazılıyor...`) to the message box. | Active while listening. | Clicking again during `Yazılıyor...` force-aborts waiting. |
| **Sensitivity Menu (`Sessiz` / `Normal` / `Gürültülü`)** | Adjusts VAD noise/speech threshold (`state.json` persisted). | Always enabled (works live during listening). | Use `Sessiz` for quiet mics/rooms, `Gürültülü` in noisy environments. |
| **Audio Level Meter** | Live level bar + red threshold marker. **Blue** = audio present below threshold; **Green** = speech detected & queued to Whisper. | Active while listening/stopping. | Shows `⚠ Ses gelmiyor` if zero mic samples arrive for 3.5s. |
| **`🎙 Mikrofon:` Dropdown** | Always-visible microphone selector on the main screen. | **Always works:** sets next mic when idle; **live hot-switches** (aborts old stream & starts new device immediately) if changed while listening/loading! | Disabled/empty only if Windows reports no input devices. |
| **`↻ Yenile`** | Re-scans Windows input devices (e.g. newly plugged USB/Bluetooth headsets). | Always enabled. | — |

### 4.3 Left Column — Cards 2 & 3: Hashtags & Topic

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **Hashtags Box** (`Hashtag'ler`) | Appended verbatim below every sent/replied/quoted message (saved in `hashtags.txt`). Does not auto-prepend `#`. | Always editable. | Only tokens starting with `#` appear as rows in the bottom-right **Hashtag İşaretleme** panel. |
| **Topic Box** (`Konu`) | Topic prompt used by both `✦ WebGPU Mesaj Üret` and `⚡ Bulut Model Üret` (saved in `state.json`). | Always editable. | If left empty, both AI text generation buttons refuse to run with a warning. |

### 4.4 Right Column — Card 1: AI Message Generation

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **`Çeşitlilik` Slider (`0.3–1.3`)** | Sets generation `temperature` (saved in `state.json`). | Always active. | — |
| **`✦ WebGPU Mesaj Üret`** | Generates Turkish copy inside Chrome WebGPU rotating through 7 rhetorical angles (`yzmodel/prompt.json`). | Works when **Topic** is non-empty, no other text generation is running (`!gen_busy`), and Chrome/WebGPU are available. | Fails/warns if Topic is empty, WebGPU is unsupported, or Chrome fails; disabled while generating. |
| **`⚡ Bulut Model Üret`** | Calls any OpenAI-compatible chat API to generate copy (auto-expands short outputs when `X-UY` is off). | Works when **Topic**, **Base URL**, **Model**, and **API Key** are **all** filled and `!gen_busy` (does **not** need Chrome). | Refuses with a warning if any of the 4 fields is empty; disabled while generating. |
| **`Base URL` / `Model` / `API Key`** | Cloud provider settings (`API Key` masked; saved in `state.json`). | Always editable. | `API Key` is also used by `✦ YZ Resim Üret` (must be an OpenRouter key for images). |

### 4.5 Right Column — Card 2: Actions & Media

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **`Yeni Gönderi`** | Publishes a new top-level post when checked. | Always toggable. | Having only `Yeni Gönderi` checked with both empty text and no active image keeps `Gönder ↗` disabled. |
| **`Link:` + URL Field** | Enables targeting an existing X post URL (`/status/<ID>`) and unlocks the 5 action chips below. | Always toggable. | When unchecked, both the URL box and all 5 chips (`Reply`, `Quote`, `Like`, `Repost`, `Bookmark`) are **disabled**. |
| **`Reply`** | Posts message (+ image) as a reply to the target link. | Only enabled when `Link:` is checked; requires valid link + text or active image. | Disabled if `Link:` is unchecked; errors if text & image are both empty. |
| **`Quote`** | Posts a Quote tweet referencing the target link. | Only enabled when `Link:` is checked; requires valid link + text or active image. | Disabled if `Link:` is unchecked; errors if text & image are both empty. |
| **`Like`** / **`Repost`** / **`Bookmark`** | Performs reaction on the target post (skips if already done). | Only enabled when `Link:` is checked + valid status link (works even with empty message box). | Disabled if `Link:` is unchecked. |
| **`Resim Ekle`** | Attaches the selected/generated image to New Post, Reply, and Quote actions. | Always toggable. | When unchecked, `Dosya Seç...`, `✦ YZ Resim Üret`, and `✕` are **disabled**, and no media is uploaded. |
| **`Dosya Seç...`** | Opens file picker for `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`. | Enabled when `Resim Ekle` is checked and `!img_busy`. | Disabled when `Resim Ekle` is unchecked or image generation is busy. |
| **`✦ YZ Resim Üret`** | Generates a poster via OpenRouter Recraft and saves it under `generated_images/`. | Enabled when `Resim Ekle` is checked and `!img_busy`; requires **OpenRouter `API Key`**, **non-empty message box**, and **internet**. | Button disabled when `Resim Ekle` is off or generating; warns & stops if `API Key` or message box is empty. |
| **`✕` (Clear Image)** | Clears attached image and closes preview popup. | Enabled only when `Resim Ekle` is checked, `!img_busy`, and an image is loaded. | Disabled otherwise. |
| **Thumbnail Box** | Clicking opens a full-resolution preview modal (`Esc` closes). | Active only when a valid image file is loaded. | Ignored when empty/missing. |

### 4.6 Right Column — Card 3: Hashtag Marking (`30+` Posts)

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **Row `Like` / `Repost`** | Selects actions per `#hashtag` found in the Hashtags box (persisted in `state.json`). | Shown automatically whenever `#word` tokens exist in `Hashtag'ler`. | Not shown if no `#` tokens exist. |
| **`İşaretle`** | Opens Chrome on X search for that `#hashtag`, scrolls, and applies `Like`/`Repost` across **at least 30 posts**. | Enabled when `!busy` and at least one of `Like`/`Repost` is checked on that row (requires logged-in X Chrome session). | Disabled while sending/marking (`busy`); refuses with a warning if neither `Like` nor `Repost` is checked. |

### 4.7 Bottom Fixed Bar

| Control | Function | When It Works | When It Doesn't Work / Limits |
|---|---|---|---|
| **`Gönder ↗`** | Runs queued actions in order (`Yeni Gönderi` first, then `Like → Bookmark → Repost → Reply → Quote`). | Enabled when `!busy` and at least one complete action is configured (`Yeni Gönderi` + text/image OR `Link:` + URL + chip). | Disabled if no work is ready or while `busy`; blocks if `Link:` is checked without URL/chips; prompts for X login if Chrome session isn't logged in. |
| **`x: @mkaragulle71` / `YouTube: @MixedMixedInfo`** | Opens author X DM/profile or YouTube channel in Chrome. | Always active (1.5s double-click debounce). | Falls back to default browser if CDP Chrome isn't reachable. |

---

## 5. Keyboard Shortcuts & Double-Send Protection

- **`Ctrl + Enter`** *(inside Message Box):* Triggers **`Gönder ↗`**.
- **`Enter` / `Esc`** *(inside Microphone Permission modal):* `Enter` grants permission & starts; `Esc` cancels.
- **`Esc`** *(inside Large Image Preview popup):* Closes preview.
- **90-Second Double-Send Guard:** Clicking `Gönder ↗` (or `Ctrl+Enter`) again within 90 seconds with the exact same text and image displays a warning instead of posting immediately. Press **`Gönder ↗` a second time** to confirm re-sending.

---

## 6. Live Statistics and Offline Queue

X Poster tracks usage via three **CounterAPI v2** counters using Bearer authentication (`GET .../up`):
1. **`atilan-mesaj-adedi`:** `+1` for each verified published New Post, Reply, or Quote *(Like, Repost, Bookmark, Hashtag marking, and failed sends do not increment)*.
2. **`webgpu-adedi`:** `+1` for each message generated via `✦ WebGPU Mesaj Üret` or `⚡ Bulut Model Üret`.
3. **`uretilen-resim`:** `+1` for each image generated via `✦ YZ Resim Üret` *(file picker selections do not increment)*.

**Offline & Restart Persistence:**
- Every increment is atomically written to [pending_stats.json](pending_stats.json) first and immediately flushed in the background.
- If the internet or API is unreachable, remaining increments stay safely stored on disk and retry in the background (`15s`–`120s` backoff); closing and reopening the app automatically flushes any queued counts upon startup once access returns, then removes the queue file when empty.

---

## 7. Project Files and Stored Data

| File / Folder | Purpose |
|---|---|
| `baslat.bat` / `xpost.bat` | One-click launchers (windowless `pyw` / console `py`). |
| `xpost.py` | Main UI, X Playwright automation, Cloud/Image clients, and CounterAPI sync queue. |
| `xpost_stt.py` | Standalone local Turkish STT engine (`sounddevice` + VAD + `faster-whisper`). |
| `yzmodel/model.html`, `yzmodel/prompt.json` | Local WebGPU LLM bridge page and shared Turkish prompt configuration. |
| `stt_models/whisper-large-v3-turbo/` | Cached local Whisper model files. |
| `generated_images/` | AI-generated images saved by `✦ YZ Resim Üret`. |
| `ChromeProfile/` | Dedicated persistent Chrome profile storing your X session (do not delete or share). |
| `hashtags.txt` | Saved hashtag/suffix block. |
| `state.json` / `state.json.bak` | Persisted topic, Cloud settings, checkboxes, image path, theme, sensitivity, and pane positions. *(Mic permission always resets cleanly on launch.)* |
| `pending_stats.json` | Present only while unsent CounterAPI increments are queued offline/at shutdown; automatically deleted once synced. |

---

## 8. Troubleshooting

- **Audio bar moves in blue, nothing types into the box:** Raw Windows mics without browser AGC may sit below the red threshold marker (which turns **green** when speech triggers Whisper). Switch sensitivity to **`Sessiz`**, increase Windows microphone level/boost, or pick another driver entry (e.g., `WASAPI` / `DirectSound`) in `🎙 Mikrofon:`.
- **`Mikrofon açılamadı` / `⚠ Ses gelmiyor`:** Check **Windows Settings → Privacy & security → Microphone** allows desktop apps, then click `↻ Yenile`.
- **Chrome not found:** Add your `chrome.exe` path to `CHROME_CANDIDATES` inside `xpost.py`.
- **Port 9222 conflict:** Close leftover automation Chrome windows or update `CDP_PORT` inside `xpost.py`.
- **Image generation fails:** Verify `Resim Ekle` is checked, the message box is non-empty, internet is connected, and the Cloud **`API Key`** holds a valid **OpenRouter** key.
