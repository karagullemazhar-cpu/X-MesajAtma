# -*- coding: utf-8 -*-
"""
X Poster — kendi X hesabına, açık Chrome penceresi üzerinden mesaj atan basit uygulama.

Nasıl çalışır:
  * Uygulama, kendine ait bir Chrome profili (ChromeProfile/) kullanır ve Chrome'u
    uzaktan hata ayıklama portu (CDP, 9222) ile başlatır. Chrome 136+ güvenlik
    kuralı gereği mevcut varsayılan profile dışarıdan bağlanılamadığı için
    ilk çalıştırmada ayrı bir Chrome penceresi açılır ve orada X'e BİR KEZ
    giriş yapılır. Giriş bu profilde kalıcıdır.
  * Sonrasında "Gönder"e her basışta uygulama açık x.com sekmesini bulur,
    mesaj kutusunu açar, yazıyı yazar ve paylaşır. Chrome kapalıysa
    aynı profille tekrar açar (giriş hâlâ geçerlidir).
"""

import base64
import functools
import html
import http.server
import io
import json
import math
import os
import queue
import random
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from tkinter import filedialog, scrolledtext

try:
    from PIL import Image as _PilImage, ImageTk as _PilImageTk
    _PIL_OK = True
except Exception:
    _PilImage = _PilImageTk = None
    _PIL_OK = False

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from xpost_stt import NativeSTTController, list_input_devices, SENSITIVITIES as _STT_SENS

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(APP_DIR, "ChromeProfile")
HASHTAGS_FILE = os.path.join(APP_DIR, "hashtags.txt")
GENERATED_DIR = os.path.join(APP_DIR, "generated_images")
YZ_DIR = os.path.join(APP_DIR, "yzmodel")          # YZ sayfası burada
YZ_PORT = 8765
YZ_URL = f"http://127.0.0.1:{YZ_PORT}/model.html"
YZ_VERSION = 5                                     # model.html'deki YZ_VERSION ile aynı olmalı
_STT_SENS_LABELS = {"Sessiz": "quiet", "Normal": "normal", "Gürültülü": "noisy"}
STATE_FILE = os.path.join(APP_DIR, "state.json")   # tüm girilen bilgiler burada saklanır
OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
IMAGE_MODEL = "recraft/recraft-v4.1-flash-v2:free"
IMAGE_RATIOS = ("9:16", "16:9")
MAX_MEDIA_BYTES = 4_800_000
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/post"
AUTHOR_X_HANDLE = "mkaragulle71"
AUTHOR_YT_HANDLE = "MixedMixedInfo"
LIMIT = 280
STATS_QUEUE_FILE = os.path.join(APP_DIR, "pending_stats.json")
COUNTER_BASE_URL = "https://api.counterapi.dev/v2/mazhar-karagulles-team-6271"
COUNTER_API_KEY = "ut_bEax6SmS9TYh9Mc6digQDlHM3m2nGj9xHHFTzeEP"
COUNTER_POST = "atilan-mesaj-adedi"
COUNTER_AI_MSG = "webgpu-adedi"
COUNTER_IMAGE = "uretilen-resim"


class _CounterSync:
    """CounterAPI v2 istatistiklerini canlı gönderir; çevrimdışı/kapanmada kuyruğu diske saklar."""

    def __init__(self, base_url=None, api_key=None, stats_file=None, retry_delay=15.0):
        self._custom_base = base_url
        self._custom_key = api_key
        self._custom_file = stats_file
        self._retry_delay = float(retry_delay)
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._pending = {}
        self._loaded_path = None
        self._flushing = False
        self._timer = None
        self._closed = False
        self._backoff = self._retry_delay

    def _cfg(self):
        base = (COUNTER_BASE_URL if self._custom_base is None else self._custom_base).strip().rstrip("/")
        key = (COUNTER_API_KEY if self._custom_key is None else self._custom_key).strip()
        path = STATS_QUEUE_FILE if self._custom_file is None else self._custom_file
        return base, key, path

    def _ensure_loaded_locked(self):
        _, _, path = self._cfg()
        if self._loaded_path == path:
            return
        self._loaded_path = path
        self._pending = {}
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        iv = int(v)
                        if isinstance(k, str) and iv > 0:
                            self._pending[k] = iv
            except Exception:
                self._pending = {}

    def _save_locked(self):
        _, _, path = self._cfg()
        if not path:
            return
        clean = {k: int(v) for k, v in self._pending.items() if int(v) > 0}
        if not clean:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            return
        tmp_path = None
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".stats_", suffix=".tmp", dir=parent or None)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f, ensure_ascii=False)
            os.replace(tmp_path, path)
            tmp_path = None
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def pending_snapshot(self):
        with self._lock:
            self._ensure_loaded_locked()
            return {k: int(v) for k, v in self._pending.items() if int(v) > 0}

    def record(self, slug, n=1, flush=True):
        if not slug or int(n) <= 0:
            return
        base, key, _ = self._cfg()
        if not base or not key:
            return
        with self._lock:
            self._ensure_loaded_locked()
            self._pending[slug] = self._pending.get(slug, 0) + int(n)
            self._save_locked()
            self._closed = False
        if flush:
            self.flush_async()

    def _send_one(self, base, key, slug):
        if not base or not key:
            return False
        url = f"{base}/{urllib.parse.quote(slug, safe='')}/up"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {key}", "User-Agent": "XPoster/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                resp.read()
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception:
            return False

    def _schedule_retry(self):
        with self._lock:
            if self._closed or not any(v > 0 for v in self._pending.values()):
                return
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
            delay = self._backoff
            self._backoff = min(120.0, max(self._retry_delay, self._backoff * 2.0))
            t = threading.Timer(delay, self.flush_async)
            t.daemon = True
            self._timer = t
            t.start()

    def flush_once(self):
        with self._flush_lock:
            with self._lock:
                self._ensure_loaded_locked()
                slugs = sorted(k for k, v in self._pending.items() if int(v) > 0)
            if not slugs:
                self._backoff = self._retry_delay
                return True
            base, key, _ = self._cfg()
            if not base or not key:
                return True
            for slug in slugs:
                while True:
                    with self._lock:
                        rem = int(self._pending.get(slug, 0))
                        closed = self._closed
                    if rem <= 0 or closed:
                        break
                    if self._send_one(base, key, slug):
                        with self._lock:
                            cur = int(self._pending.get(slug, 0))
                            if cur > 1:
                                self._pending[slug] = cur - 1
                            elif slug in self._pending:
                                del self._pending[slug]
                            self._save_locked()
                        self._backoff = self._retry_delay
                    else:
                        self._schedule_retry()
                        return False
            return True

    def flush_async(self):
        with self._lock:
            self._ensure_loaded_locked()
            base, key, _ = self._cfg()
            if self._closed or self._flushing or not base or not key or not any(v > 0 for v in self._pending.values()):
                return False
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            self._flushing = True

        def _worker():
            ok = False
            try:
                ok = self.flush_once()
            finally:
                with self._lock:
                    self._flushing = False
            if ok and not self._closed and self.pending_snapshot():
                self.flush_async()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def reopen_and_flush(self):
        with self._lock:
            self._closed = False
            self._backoff = self._retry_delay
            self._loaded_path = None
            self._ensure_loaded_locked()
        self.flush_async()

    def close(self, wait_timeout=0.35):
        with self._lock:
            self._closed = True
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            self._ensure_loaded_locked()
            self._save_locked()
        deadline = time.monotonic() + max(0.0, float(wait_timeout))
        while time.monotonic() < deadline:
            with self._lock:
                if not self._flushing:
                    break
            time.sleep(0.02)
        with self._lock:
            self._save_locked()


_stats_sync = _CounterSync()


def track_counter(slug, n=1):
    _stats_sync.record(slug, n=n)

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]

# X arayüzünde yıllardır sabit kalan data-testid seçicileri.
# ÖNEMLİ: Ana sayfadaki gizli satır-içi composer da "tweetTextarea_0"/"tweetButtonInline"
# kullanır; bunlara değil, yalnızca açılan mesaj PENCERESİNE (role="dialog") bakılmalı.
SEL_SIDEBAR_POST = '[data-testid="SideNav_NewTweet_Button"]'
SEL_DIALOG_TEXTAREA = '[role="dialog"] [data-testid="tweetTextarea_0"]'
SEL_DIALOG_POST = '[role="dialog"] [data-testid="tweetButton"]'
SEL_TOAST = '[data-testid="toast"]'
SEL_ACCOUNT = '[data-testid="SideNav_AccountSwitcher_Button"]'


# ---------------------------------------------------------------- tarayıcı

def cdp_alive(timeout=1.0):
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def find_chrome():
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    return shutil.which("chrome") or shutil.which("chrome.exe")


def ensure_chrome(log):
    """CDP'ye açık bir Chrome yoksa, uygulamaya özel profille başlat."""
    if cdp_alive():
        return True
    chrome = find_chrome()
    if not chrome:
        log("Chrome bulunamadı! Google Chrome kurulu mu? (Yolu xpost.py içinden düzenleyebilirsin.)", error=True)
        return False
    log("Chrome başlatılıyor (uygulamaya özel profil)...")
    proc = subprocess.Popen([
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        HOME_URL,
    ])
    exited_at = None
    for _ in range(60):
        if cdp_alive():
            return True
        if proc.poll() is not None:
            if exited_at is None:
                exited_at = time.time()
            elif time.time() - exited_at >= 6.0:
                break
        time.sleep(0.5)
    log("Chrome'a bağlanılamadı. Aynı profille açık başka Chrome penceresi varsa kapatıp tekrar dene.", error=True)
    return False


# ---------------------------------------------------------------- YZ (tarayıcı içi model)

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
    }

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _DaemonTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


_yz_server_err = None
_local_server_lock = threading.Lock()
_local_server_port = None
_local_httpd = None


def local_base_url():
    return f"http://127.0.0.1:{_local_server_port or YZ_PORT}"


def _yz_url():
    return f"{local_base_url()}/model.html"


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ensure_local_server():
    """YZ dosyalarını yalnız 127.0.0.1 üzerinde tek sunucuda başlat."""
    global _yz_server_err, _local_server_port, _local_httpd
    with _local_server_lock:
        if _local_httpd is not None:
            return True
        handler = functools.partial(_QuietHandler, directory=YZ_DIR)
        last_err = None
        for port in range(YZ_PORT, YZ_PORT + 20):
            if _port_in_use(port):
                last_err = f"{port} portu kullanımda"
                continue
            try:
                httpd = _DaemonTCPServer(("127.0.0.1", port), handler)
            except Exception as e:
                last_err = str(e)
                continue
            _local_httpd = httpd
            _local_server_port = port
            _yz_server_err = None
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            return True
        _yz_server_err = last_err or "boş yerel port bulunamadı"
        return False


def _serve_yz():
    """Yerel YZ & STT HTTP sunucusunu arka planda başlat (eski giriş noktası)."""
    _ensure_local_server()


def _clean_yz(text, limit=230):
    """Model çıktısını temizle: düşünme blokları, kod çitleri, etiket önekleri,
    hashtag/emoji/tırnak at; tek paragraf yap, çok uzansa cümle sonundan kes."""
    t = (text or "").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)   # Qwen3 düşünme bloğu
    if "</think>" in t:                                     # şablon <think> açılışını yutmuşsa
        t = t.split("</think>", 1)[1]
    t = re.sub(r"<think>.*$", "", t, flags=re.S)            # yarım kalmış düşünme bloğu
    t = re.sub(r"```[a-zA-Z]*", "", t).strip()              # markdown kod çiti
    t = re.sub(r"^(?:[cç][ıi]kt[ıi]|tweet|metin|yan[ıi]t|payla[şs][ıi]m)\s*[:\-]\s*", "", t, flags=re.I)
    t = t.strip().strip('"\'“”‘’`').replace("**", "").replace("__", "")
    t = t.strip().strip('"\'“”‘’`').strip()
    t = re.sub(r"#[^\s#]+", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]", "", t)
    t = re.sub(r"\s+", " ", t).strip().strip('"\'“”‘’`').strip()
    if len(t) > limit:
        window = t[:limit + 1]
        ends = [m.start() + 1 for m in re.finditer(r"[.!?](?=\s|$)", window)]
        idx = ends[-1] if ends and ends[-1] > 60 else -1
        if idx > 0:
            t = window[:idx].strip()
        else:
            cut = t[:limit]
            t = (cut.rsplit(" ", 1)[0] if " " in cut else cut).strip()
    return t


def _yz_prompts():
    """prompt.json'dan ortak Türkçe system prompt'u ve üslup açılarını oku
    (WebGPU ve bulut modeli AYNI kaynağı kullanır)."""
    try:
        with open(os.path.join(YZ_DIR, "prompt.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("system", ""), cfg.get("angles", [])
    except Exception:
        return "", []


def _extract_choice_content(msg):
    """OpenAI uyumlu message.content alanını metin olarak çıkar (string veya parça listesi)."""
    raw = msg.get("content")
    if isinstance(raw, list):
        parts = [p.get("text", "") for p in raw if isinstance(p, dict) and p.get("type") == "text"]
        return "".join(parts).strip()
    return (raw or "").strip()


_CLOUD_RETRY_DELAYS = (2.0, 4.0)


def _split_topic_points(topic):
    """Konu metnini tekrarlanmayacak anlamlı alt maddelere/cümlelere böler."""
    text = (topic or "").strip()
    if not text:
        return []
    raw_lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    parts = []
    for ln in raw_lines:
        clean_ln = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", ln).strip()
        if len(clean_ln) > 90:
            subs = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\s*;\s*", clean_ln) if s.strip()]
            parts.extend(subs if len(subs) > 1 else [clean_ln])
        elif clean_ln:
            parts.append(clean_ln)
    pts = [p for p in parts if len(p) >= 12]
    return pts or parts


def _pick_focus_points(topic, used_focuses, k=3):
    """Konuda birden fazla alt madde varsa son seçilenleri tekrar etmeden k odak seçer."""
    pts = _split_topic_points(topic)
    if len(pts) <= 1:
        return []
    count = min(k, max(1, len(pts) - 1)) if len(pts) <= 4 else min(k, len(pts))
    unused = [p for p in pts if p not in used_focuses]
    if len(unused) >= count:
        chosen = random.sample(unused, count)
        used_focuses.extend(chosen)
    else:
        used_pool = [p for p in pts if p not in unused]
        need = min(count - len(unused), len(used_pool))
        chosen = list(unused) + random.sample(used_pool, need)
        random.shuffle(chosen)
        used_focuses[:] = list(chosen)
    return chosen


def _build_yz_user_prompt(topic, tags, angle, cap, note, focus="", avoid=""):
    """WebGPU ve bulut modeller için ortak kullanıcı istemini kurar."""
    parts = [
        "Konu: " + topic,
        "Hashtagler: " + (tags or "(yok)"),
        "Üslup yönergesi: " + angle,
        "Uzunluk: " + note + ". En fazla " + str(cap) + " karakter.",
    ]
    if focus:
        parts.append(
            "Bu paylaşımda özellikle şu alt noktalara odaklan (tüm maddeleri listeleme): " + focus
        )
    if avoid:
        parts.append("Önceki şu başlangıçları ve kalıpları TEKRARLAMA: " + avoid)
    parts.append("Çıktı:")
    return "\n".join(parts)


_IMAGE_STYLES = (
    "bold high-contrast social media editorial graphic poster with a clean symbolic center visual and crisp bold condensed sans-serif Turkish headline text",
    "candid documentary street photojournalism showing ordinary citizens holding a clean readable cardboard protest sign with bold black Turkish lettering",
    "modern investigative news magazine cover composition with dramatic symbolic scene and a razor-sharp Turkish headline banner across a dark band",
    "minimalist dark-slate typographic concept poster combining one powerful symbolic object metaphor with large clean off-white Turkish slogan lettering",
    "atmospheric evening city street photography where an illuminated urban billboard or poster wall clearly displays the bold Turkish headline",
    "dramatic close-up editorial photography of official financial documents or empty wallet beside a crisp bold stamped Turkish headline phrase",
    "expressive modern editorial illustration poster depicting the real conflict visually with bold clean integrated Turkish display typography",
    "cinematic twilight glass window view overlooking city lights bearing clean bold white printed Turkish headline lettering across the glass",
)


def _cloud_headers(api_key, is_openrouter=False):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
        "User-Agent": "XPoster/1.0",
    }
    if is_openrouter:
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "X Poster"
    return headers


def _post_json_with_retry(url, payload, headers, timeout=180, advance_codes=()):
    """JSON POST isteğini 429/5xx geçici hatalarında bekleterek yineler."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for try_idx in range(len(_CLOUD_RETRY_DELAYS) + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if e.code in (429, 502, 503, 504):
                if try_idx < len(_CLOUD_RETRY_DELAYS):
                    time.sleep(_CLOUD_RETRY_DELAYS[try_idx])
                    continue
                msg = ("bulut sağlayıcı istek sınırına ulaştı (HTTP 429 — kısa süre bekleyip tekrar deneyin)"
                       if e.code == 429 else f"bulut sağlayıcı geçici hata verdi (HTTP {e.code})")
                raise RuntimeError(f"{msg}: {detail}")
            err = RuntimeError(f"bulut sağlayıcı hata verdi (HTTP {e.code}): {detail}")
            if e.code in advance_codes:
                return None, err
            raise err
        except urllib.error.URLError as e:
            raise RuntimeError(f"bulut sağlayıcıya ulaşılamadı: {e.reason}")
    raise RuntimeError("bulut çağrısı başarısız")


def _cloud_chat(base_url, api_key, model, system, user, timeout=180, temperature=1.0):
    """OpenAI uyumlu /chat/completions çağrısı (stdlib, ek bağımlılık yok).
    OpenRouter'da reasoning kapama/azaltma seçeneklerini sırayla dener;
    boş veya hata yanıtlarında teşhis bilgisini hata mesajına ekler."""
    url = base_url.strip().rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    is_or = "openrouter" in host
    temp = max(0.0, min(2.0, float(temperature)))

    base_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": round(temp, 2),
        "max_tokens": 4096,   # düşünme (reasoning) zorunlu modeller için bol tutulur
    }
    # OpenRouter: önce reasoning'i tamamen kapat (örn. ling-3.2), reddederse minimal'e
    # düşür (örn. ernie), olmazsa exclude / sade gövdeyle devam et.
    attempts = []
    if is_or:
        for r_cfg in (
            {"enabled": False},
            {"effort": "minimal", "exclude": True},
            {"exclude": True},
        ):
            p = dict(base_payload)
            p["reasoning"] = r_cfg
            attempts.append(p)
    attempts.append(dict(base_payload))

    headers = _cloud_headers(api_key, is_openrouter=is_or)
    last_err = None
    for idx, payload in enumerate(attempts):
        has_next = idx < len(attempts) - 1
        adv = (400, 404, 422) if has_next else ()
        data, err = _post_json_with_retry(url, payload, headers, timeout=timeout, advance_codes=adv)
        if data is None:
            last_err = err
            continue

        snippet = json.dumps(data, ensure_ascii=False)[:300]
        if isinstance(data, dict) and data.get("error"):
            e0 = data["error"]
            msg = e0.get("message") if isinstance(e0, dict) else str(e0)
            last_err = RuntimeError(f"sağlayıcı hata döndürdü: {str(msg)[:200]} | ham: {snippet}")
            err_code = e0.get("code") if isinstance(e0, dict) else None
            if err_code in (400, 404, 422) and has_next:
                continue
            raise last_err
        try:
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            content = _extract_choice_content(msg)
        except Exception:
            raise RuntimeError("bulut yanıtı beklenmedik biçimde | ham: " + snippet)
        if content:
            return content
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        extra = " (yalnızca düşünme çıktısı verdi — normal bir sohbet modeli kullanın)" if reasoning else ""
        last_err = RuntimeError("bulut model BOŞ yanıt döndürdü" + extra + " | ham: " + snippet)
        if has_next:
            continue
        raise last_err

    raise last_err or RuntimeError("bulut çağrısı başarısız")


def _openrouter_images_url(base_url):
    """OpenRouter temel adresinden /api/v1/images uç noktasını üretir."""
    u = (base_url or "").strip().rstrip("/")
    if "openrouter" not in u.lower():
        return OPENROUTER_IMAGES_URL
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    if u.endswith("/images"):
        return u
    if re.search(r"/v\d+$", u):
        return u + "/images"
    p = urllib.parse.urlparse(u)
    return f"{p.scheme}://{p.netloc}/api/v1/images"


def _next_image_style(used_styles):
    pool = [s for s in _IMAGE_STYLES if s not in used_styles]
    src = pool or list(_IMAGE_STYLES)
    st = random.choice(src)
    used_styles.append(st)
    if len(used_styles) > 6:
        used_styles.pop(0)
    return st


def _strip_social_tokens(text):
    t = re.sub(r"https?://\S+", " ", text or "")
    t = re.sub(r"[#@][\wçğıöşüÇĞİÖŞÜ]+", " ", t)
    return " ".join(t.split()).strip()


_IMAGE_SCENE_SYSTEM = (
    "You are an editorial graphic designer and art director for Turkish social media (X) posts. "
    "Convert the given Turkish post into ONE vivid English prompt (35-65 words) for Recraft V4.1 Flash V2 "
    "that pairs a concrete meaningful visual scene with crisp, legible Turkish headline text inside the image.\n"
    "Rules:\n"
    "1) First distill ONE short, punchy Turkish headline/slogan directly from the message (2 to 4 short words MAX, "
    "under 24 characters, ALL CAPS in accurate Turkish alphabet with Ç, Ğ, İ, Ö, Ş, Ü — e.g. \"HAKKIMIZI VERİN\", \"ANAPARA + TÜFE ÖDENSİN\").\n"
    "2) Include that exact Turkish slogan inside quotes as visible text on a poster, news banner, placard, "
    "or typographic layout: e.g. reading \"<SLOGAN>\". Keep ONLY that one phrase in quotes so lettering stays razor-sharp.\n"
    "3) Build the concrete visual scene directly around the post's true topic and emotion using tangible objects, "
    "places, and ordinary people (NEVER unrelated generic scenery).\n"
    "4) Do NOT name or depict real politicians/public figures; depict affected ordinary citizens, buildings, or symbolic objects.\n"
    "5) Exclude hashtags, @mentions, URLs, tiny illegible filler words on background papers/calendars/clothes, and watermarks.\n"
    "6) Reply ONLY with the final prompt in one paragraph — no preamble or labels."
)

_IMAGE_SCENE_FALLBACK_MODELS = (
    "baidu/ernie-5.5-flash-preview:free",
    "inclusionai/ling-3.2-flash:free",
)


def _tr_upper(text):
    return (text or "").replace("i", "İ").replace("ı", "I").upper()


def _extract_short_turkish_headline(text):
    """Mesajdan afiş/görsel içine sığacak 2-5 kelimelik vurucu Türkçe başlık çıkarır."""
    cleaned = _strip_social_tokens(text)
    if not cleaned:
        cleaned = " ".join((text or "").replace("#", " ").replace("@", " ").split()).strip()
    parts = [p.strip(" .,!?:;\"'") for p in re.split(r"[.!?\n;]+", cleaned) if p.strip(" .,!?:;\"'")]
    pick = ""
    for p in parts:
        words = p.split()
        if 2 <= len(words) <= 5:
            pick = p
            break
    if not pick:
        words = (parts[0] if parts else cleaned).split()
        pick = " ".join(words[:4])
    return _tr_upper(pick)


def _clean_msg_for_image(message):
    msg_clean = _strip_social_tokens(message)
    if not msg_clean:
        msg_clean = " ".join((message or "").replace("#", " ").replace("@", " ").split()).strip()
    if len(msg_clean) > 420:
        msg_clean = msg_clean[:420].rsplit(" ", 1)[0]
    return msg_clean


def _build_image_prompt(message, used_styles, used_focuses=None):
    """Mesaj kutusundaki metinden Türkçe sloganlı yerel yedek görsel istemi kurar."""
    style = _next_image_style(used_styles) if isinstance(used_styles, list) else str(used_styles)
    msg_clean = _clean_msg_for_image(message)
    focus_pts = _pick_focus_points(msg_clean, used_focuses, k=1) if (used_focuses is not None and msg_clean) else []
    core = focus_pts[0] if focus_pts else msg_clean
    slogan = _extract_short_turkish_headline(core)
    slogan_part = f', featuring crisp bold typography reading "{slogan}"' if slogan else ""
    prompt = (
        f"{style}. Visual theme representing: {core[:220]}{slogan_part}. "
        "Clean high-contrast editorial composition, ultra sharp, no watermark."
    )
    return prompt, style


def _translate_message_to_image_prompt(message, api_key, base_url="", model="",
                                       style="", focus="", log=None):
    """Türkçe mesajı içinde Türkçe başlık barındıran somut görsel istemine çevirir."""
    msg_clean = _clean_msg_for_image(message)
    if not msg_clean:
        return _build_image_prompt(message, style or _IMAGE_STYLES[0])[0]

    suggested_slogan = _extract_short_turkish_headline(focus or msg_clean)
    user = (
        f"Turkish post:\n{msg_clean}\n"
        + (f"\nFocus line from post: {focus}\n" if focus else "")
        + (f"\nSuggested short Turkish slogan option: \"{suggested_slogan}\"\n" if suggested_slogan else "")
        + (f"\nVisual layout & style format: {style}\n" if style else "")
        + "\nWrite the Recraft image prompt with ONE short Turkish headline in quotes, no extra text/watermark:"
    )

    candidates = []
    b_clean = (base_url or "").strip().rstrip("/") or "https://openrouter.ai/api/v1"
    m_clean = (model or "").strip()
    if m_clean:
        candidates.append((b_clean, m_clean))
    or_base = b_clean if "openrouter" in b_clean.lower() else "https://openrouter.ai/api/v1"
    for fb in _IMAGE_SCENE_FALLBACK_MODELS:
        pair = (or_base, fb)
        if pair not in candidates:
            candidates.append(pair)

    for c_base, c_model in candidates:
        try:
            raw = _cloud_chat(c_base, api_key, c_model, _IMAGE_SCENE_SYSTEM, user, timeout=45, temperature=0.7)
            cleaned = re.sub(r"^(?:image\s*)?prompt\s*:\s*", "", (raw or "").strip(), flags=re.I)
            cleaned = " ".join(cleaned.strip('` ').split())
            if cleaned.startswith('"') and cleaned.endswith('"') and cleaned.count('"') == 2:
                cleaned = cleaned[1:-1].strip()
            if len(cleaned) >= 20:
                if "watermark" not in cleaned.lower():
                    cleaned += ", ultra sharp, no watermark"
                if len(cleaned) > 520:
                    cleaned = cleaned[:520].rsplit(" ", 1)[0]
                return cleaned
        except Exception as e:
            if log:
                log(f"Sahne çevirisi ({c_model}) atlandı: {str(e)[:80]}")
            continue

    if log:
        log("İngilizce sahne çevirisi alınamadı — doğrudan mesajla görsel üretiliyor.")
    return _build_image_prompt(msg_clean, style or _IMAGE_STYLES[0])[0]


def _decode_data_uri(uri):
    m = re.match(r"^data:([^;]+);base64,(.+)$", uri or "", re.S)
    if not m:
        return None, ""
    return base64.b64decode(m.group(2)), m.group(1).lower()


def _extract_generated_image_bytes(data):
    """OpenRouter /images (veya multimodal chat) yanıtından ham görsel baytlarını çıkarır."""
    snippet = json.dumps(data, ensure_ascii=False)[:300]
    if isinstance(data, dict) and data.get("error"):
        e0 = data["error"]
        msg = e0.get("message") if isinstance(e0, dict) else str(e0)
        raise RuntimeError(f"görsel sağlayıcı hata döndürdü: {str(msg)[:200]} | ham: {snippet}")
    items = data.get("data") if isinstance(data, dict) else None
    if isinstance(items, list) and items:
        d0 = items[0] if isinstance(items[0], dict) else {}
        mtype = (d0.get("media_type") or "").lower()
        if d0.get("b64_json"):
            return base64.b64decode(d0["b64_json"]), (mtype or "image/webp")
        url_val = d0.get("url") or ""
        if url_val.startswith("data:"):
            raw, dtype = _decode_data_uri(url_val)
            if raw:
                return raw, (dtype or mtype or "image/png")
        if url_val.startswith("http"):
            with urllib.request.urlopen(urllib.request.Request(url_val, headers={"User-Agent": "XPoster/1.0"}), timeout=60) as r:
                return r.read(), (r.headers.get_content_type() or mtype or "image/png").lower()
    # Alternatif multimodal chat biçimi desteği
    try:
        imgs = data["choices"][0]["message"].get("images") or []
        u = (imgs[0].get("image_url") or {}).get("url") or ""
        if u.startswith("data:"):
            raw, dtype = _decode_data_uri(u)
            if raw:
                return raw, dtype
    except Exception:
        pass
    raise RuntimeError("görsel API çıktısında resim verisi bulunamadı | ham: " + snippet)


def _detect_image_ext(raw_bytes, media_type=""):
    mt = (media_type or "").lower()
    if "png" in mt or raw_bytes.startswith(b"\x89PNG"):
        return ".png"
    if "jpeg" in mt or "jpg" in mt or raw_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if "gif" in mt or raw_bytes.startswith(b"GIF8"):
        return ".gif"
    if "webp" in mt or (len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP"):
        return ".webp"
    return ".png"


def _prune_generated_dir(out_dir, keep=12):
    try:
        files = [os.path.join(out_dir, n) for n in os.listdir(out_dir)]
        files = [p for p in files if os.path.isfile(p)]
        if len(files) <= keep:
            return
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old in files[keep:]:
            try:
                os.remove(old)
            except Exception:
                pass
    except Exception:
        pass


def _save_generated_image(raw_bytes, media_type="", out_dir=GENERATED_DIR):
    os.makedirs(out_dir, exist_ok=True)
    ext = _detect_image_ext(raw_bytes, media_type)
    size = None
    if _PIL_OK:
        try:
            with _PilImage.open(io.BytesIO(raw_bytes)) as im:
                size = im.size
                if len(raw_bytes) > MAX_MEDIA_BYTES:
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
                    raw_bytes = buf.getvalue()
                    ext = ".jpg"
        except Exception:
            pass
    name = f"yz_img_{time.strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}{ext}"
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(raw_bytes)
    _prune_generated_dir(out_dir, keep=12)
    return path, size


def _generate_cloud_image(api_key, prompt, aspect_ratio, base_url=OPENROUTER_IMAGES_URL,
                          model=IMAGE_MODEL, out_dir=GENERATED_DIR, timeout=120):
    """OpenRouter /api/v1/images ile görsel üretir ve diske kaydeder."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        url = OPENROUTER_IMAGES_URL
    elif not url.endswith("/images"):
        url = _openrouter_images_url(url)
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    headers = _cloud_headers(api_key, is_openrouter=("openrouter" in host))
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }
    data, _ = _post_json_with_retry(url, payload, headers, timeout=timeout)
    raw_bytes, mtype = _extract_generated_image_bytes(data)
    path, size = _save_generated_image(raw_bytes, mtype, out_dir=out_dir)
    return {"path": path, "aspect_ratio": aspect_ratio, "size": size, "model": model}


class _SttCancelled(Exception):
    pass


def _find_local_tab(context, path_prefix):
    base = local_base_url()
    for p in getattr(context, "pages", ()):
        if p.is_closed():
            continue
        parsed = urllib.parse.urlparse(p.url or "")
        if f"{parsed.scheme}://{parsed.netloc}" == base and (parsed.path or "").startswith(path_prefix):
            return p
    return None


def _close_local_tabs(context, path_prefix, keep_sid=None):
    """Chrome'da kalmış/askıda yerel uygulama sekmelerini temizle (yalnızca 127.0.0.1/<path_prefix>)."""
    closed = 0
    for p in list(getattr(context, "pages", ())):
        try:
            if p.is_closed():
                continue
            parsed = urllib.parse.urlparse(p.url or "")
            if parsed.hostname != "127.0.0.1" or not (parsed.path or "").startswith(path_prefix):
                continue
            if keep_sid is not None:
                try:
                    sid = p.evaluate("() => window._xpostSid ?? null")
                    if sid == keep_sid:
                        continue
                except Exception:
                    pass
            p.close()
            closed += 1
        except Exception:
            pass
    return closed


def _ensure_web_tab(
    context,
    log,
    *,
    url,
    path_prefix,
    ready_fn_js,
    version_var,
    version,
    is_ready_js,
    start_load_js,
    get_error_js,
    get_progress_js,
    prep_msg,
    ready_msg,
    err_prefix,
    tab_closed_msg,
    cancel_cb=None,
):
    """YZ veya STT WebGPU sekmesini açar/bulur ve modeli yükler."""
    if not _ensure_local_server():
        raise RuntimeError(f"Yerel HTTP sunucusu başlatılamadı (port {YZ_PORT}): {_yz_server_err}")
    if cancel_cb and cancel_cb():
        raise _SttCancelled()

    def _wait_ready_fn(page):
        for _ in range(25):
            if cancel_cb and cancel_cb():
                try:
                    page.close()
                except Exception:
                    pass
                raise _SttCancelled()
            try:
                page.wait_for_function(ready_fn_js, timeout=1000)
                return
            except PWTimeout:
                if page.is_closed():
                    raise RuntimeError(tab_closed_msg)
                continue
        raise RuntimeError(f"{err_prefix}: sayfa betiği zamanında yüklenemedi")

    tab = _find_local_tab(context, path_prefix)
    try:
        if tab is None:
            tab = context.new_page()
            if cancel_cb and cancel_cb():
                try:
                    tab.close()
                except Exception:
                    pass
                raise _SttCancelled()
            tab.goto(url, wait_until="domcontentloaded", timeout=15000)
            _wait_ready_fn(tab)
        elif tab.evaluate(f"window.{version_var} || 0") < version:
            tab.reload(wait_until="domcontentloaded", timeout=15000)
            _wait_ready_fn(tab)
    except _SttCancelled:
        raise
    except Exception as e:
        if _yz_server_err:
            raise RuntimeError(f"Yerel YZ sunucusu başlatılamadı (port {YZ_PORT}): {_yz_server_err}") from e
        raise
    if cancel_cb and cancel_cb():
        try:
            tab.close()
        except Exception:
            pass
        raise _SttCancelled()
    if tab.evaluate(is_ready_js):
        return tab
    log(prep_msg)
    tab.evaluate(start_load_js)
    last = ""
    while True:
        if cancel_cb and cancel_cb():
            try:
                tab.close()
            except Exception:
                pass
            raise _SttCancelled()
        if tab.is_closed():
            raise RuntimeError(tab_closed_msg)
        if tab.evaluate(is_ready_js):
            log(ready_msg)
            return tab
        err = tab.evaluate(get_error_js)
        if err:
            raise RuntimeError(f"{err_prefix}: {str(err)[:160]}")
        prog = tab.evaluate(get_progress_js)
        if prog and prog != last:
            log(prog[:110])
            last = prog
        time.sleep(0.4)


def _ensure_model_tab(context, log):
    """YZ sekmesini açar/bulur ve modeli yükler; ilerleme durum satırına akar.
    Model, otomasyon Chrome'unun önbelleğine (ChromeProfile/) iner."""
    return _ensure_web_tab(
        context,
        log,
        url=_yz_url(),
        path_prefix="/model.html",
        ready_fn_js="() => typeof window.loadModel === 'function'",
        version_var="YZ_VERSION",
        version=YZ_VERSION,
        is_ready_js="window.isReady ? window.isReady() : false",
        start_load_js="() => { window._err = null; window.loadModel().catch(e => { window._err = String(e); }); }",
        get_error_js="window.lastError ? window.lastError() : null",
        get_progress_js="(document.getElementById('s')||{}).textContent || ''",
        prep_msg="YZ modeli hazırlanıyor (ilk seferde ~2 GB iner; sonrasında saniyeler)...",
        ready_msg="YZ modeli hazır ✓",
        err_prefix="YZ modeli yüklenemedi (WebGPU desteklenmiyor olabilir)",
        tab_closed_msg="YZ model sekmesi kapatıldı",
    )


# ---------------------------------------------------------------- x.com işlemleri

X_HOSTS = {
    "x.com", "www.x.com", "mobile.x.com",
    "twitter.com", "www.twitter.com", "mobile.twitter.com",
}


def find_x_page(context):
    for page in context.pages:
        if page.is_closed():
            continue
        host = (urllib.parse.urlparse(page.url).hostname or "").lower()
        if host in X_HOSTS:
            return page
    page = context.new_page()
    page.goto(HOME_URL, wait_until="domcontentloaded")
    return page


def is_logged_in(page, timeout=1500):
    try:
        page.locator(
            f'{SEL_ACCOUNT}, [data-testid="AppTabBar_Profile_Link"]'
        ).first.wait_for(state="visible", timeout=timeout)
        return True
    except PWTimeout:
        return False


def _norm(s):
    """Karşılaştırma için boşlukları, sıfır-genişlik karakterlerini ve Unicode farklarını yok say."""
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace("\u200b", "").replace("\ufeff", "")
    return "".join(s.split())


def _published_matches(body, expected, urls=None, media_urls=None, has_media=False, quoted_sid=None):
    """X'in döndürdüğü/gösterdiği metni beklenenle karşılaştır (HTML entity, t.co, medya, alıntı ve @mention destekli)."""
    exp_n = _norm(expected)
    if not exp_n:
        return False
    raw = html.unescape(body or "")
    for m_url in (media_urls or ()):
        if m_url:
            raw = raw.replace(m_url, "")
    if quoted_sid and urls:
        for u in urls:
            short = u.get("url") or ""
            exp_u = u.get("expanded_url") or ""
            if short and f"/status/{quoted_sid}" in exp_u:
                raw = raw.replace(short, "")
    variants = [raw]
    if has_media or quoted_sid:
        trimmed = re.sub(
            r"(?:\s+https?://(?:t\.co/[A-Za-z0-9]+|(?:x|twitter)\.com/\S+/status(?:es)?/\d+\S*))+$",
            "", raw,
        ).strip()
        if trimmed != raw:
            variants.append(trimmed)
    candidates = list(variants)
    if urls:
        for base in variants:
            expanded = base
            display = base
            no_scheme = base
            for u in urls:
                short = u.get("url") or ""
                if not short:
                    continue
                exp_u = u.get("expanded_url") or ""
                disp_u = u.get("display_url") or ""
                if exp_u:
                    expanded = expanded.replace(short, exp_u)
                    no_scheme = no_scheme.replace(short, re.sub(r"^https?://", "", exp_u))
                if disp_u:
                    display = display.replace(short, disp_u)
            candidates.extend([expanded, display, no_scheme])
    for cand in candidates:
        c_n = _norm(cand)
        if c_n == exp_n or c_n.endswith(exp_n):
            return True
    return False


def _get_composer(page):
    """Kutu + Gönder butonu: önce mesaj penceresine (dialog) özgü, yoksa genel seçici."""
    box = page.locator(SEL_DIALOG_TEXTAREA).first
    btn = page.locator(SEL_DIALOG_POST).first
    try:
        if box.count() and btn.count():
            return box, btn
    except Exception:
        pass
    box = page.locator('[data-testid="tweetTextarea_0"]').first
    btn = page.locator('[data-testid="tweetButton"]').first
    try:
        if btn.count():
            return box, btn
    except Exception:
        pass
    return box, page.locator('[data-testid="tweetButtonInline"]').first


def _dismiss_discard_dialog(page):
    """Açık kalmış 'Taslağı sil / Discard' onay penceresini kapat."""
    try:
        cancel = page.locator('[data-testid="confirmationSheetCancel"]').first
        if cancel.count() and cancel.is_visible():
            cancel.click(timeout=2000)
            time.sleep(0.4)
    except Exception:
        pass


def open_composer(page):
    """Mesaj penceresini aç: zaten açık -> kenar çubuğu butonu -> 'n' kısayolu -> compose adresi."""
    _dismiss_discard_dialog(page)
    try:
        if page.locator(SEL_DIALOG_TEXTAREA).first.is_visible():
            return
    except Exception:
        pass
    try:
        page.click(SEL_SIDEBAR_POST, timeout=2000)
        page.locator(SEL_DIALOG_TEXTAREA).first.wait_for(state="visible", timeout=2000)
        return
    except Exception:
        pass
    try:
        page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        page.keyboard.press("n")
        page.locator(SEL_DIALOG_TEXTAREA).first.wait_for(state="visible", timeout=2500)
        return
    except Exception:
        pass
    page.goto(COMPOSE_URL, wait_until="domcontentloaded")
    try:
        page.locator(f'{SEL_DIALOG_TEXTAREA}, [data-testid="tweetTextarea_0"]').first.wait_for(
            state="visible", timeout=10000
        )
    except Exception:
        pass


class ApiRejected(RuntimeError):
    """X'in gönderimi açıkça reddetmesi (yeniden deneme anlamsız)."""


class SubmitAttempted(RuntimeError):
    """Gönderim bir kez denendi; ne olursa olsun otomatik tekrar YAPILMAZ."""


def _box_text(box):
    try:
        return box.inner_text().replace("\u200b", "")
    except Exception:
        return ""


def _set_clipboard(page, text):
    """Metni sistem panosuna koy (gerçek Ctrl+V yapıştırması için)."""
    page.bring_to_front()
    last = None
    for _ in range(2):
        try:
            page.evaluate("t => navigator.clipboard.writeText(t)", text)
            return
        except Exception as e:
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"panoya yazılamadı ({last})")


def _insert_with(page, box, text, strat):
    """Metni verilen yöntemle yerleştir ve doğrula:
      paste = gerçek pano yapıştırması (Ctrl+V, en insansı ve atomik),
      exec  = execCommand insertText (atomik, IME durumu bırakmaz),
      type  = yavaş tuşlama (son çare)."""
    page.bring_to_front()
    box.focus()  # fare tıklaması DEĞİL: X bazen görünmez bir sabit katman binip
                 # tıklamaları yutuyor (Playwright: "intercepts pointer events").
                 # JS odaklaması katmanlardan etkilenmez.
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    time.sleep(0.3)
    if strat == "paste":
        _set_clipboard(page, text)
        box.focus()
        page.keyboard.press("Control+v")
    elif strat == "exec":
        ok = page.evaluate("t => document.execCommand('insertText', false, t)", text)
        if not ok:
            raise RuntimeError("execCommand insertText desteklenmedi")
    else:
        page.keyboard.type(text, delay=25)
    time.sleep(0.8)
    if _norm(_box_text(box)) != _norm(text):
        raise RuntimeError("kutu içeriği beklenen metinle eşleşmedi")


def _extract_tweet_from_response(data):
    """CreateTweet / CreateNoteTweet GraphQL yanıtından tam metin, kimlik ve linkleri çıkar."""
    if not isinstance(data, dict):
        return None
    d = data.get("data")
    if not isinstance(d, dict):
        return None
    node = (
        d.get("create_tweet")
        or d.get("tweet_create")
        or d.get("notetweet_create")
        or d.get("create_note_tweet")
    )
    if not isinstance(node, dict):
        for val in d.values():
            if isinstance(val, dict) and "tweet_results" in val:
                node = val
                break
    if not isinstance(node, dict):
        return None
    result = (node.get("tweet_results") or {}).get("result")
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults" and isinstance(result.get("tweet"), dict):
        result = result["tweet"]

    legacy = result.get("legacy") if isinstance(result.get("legacy"), dict) else {}
    tid = result.get("rest_id") or result.get("id") or legacy.get("id_str")

    # Uzun gönderilerde (NoteTweet >280 karakter) legacy.full_text KISALTILMIŞTIR;
    # tam metin note_tweet.note_tweet_results.result.text içindedir.
    note_res = (((result.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result")) or {}
    if not isinstance(note_res, dict):
        note_res = {}
    note_text = note_res.get("text")
    full_text = note_text if note_text is not None else legacy.get("full_text", result.get("text"))

    urls = []
    media_urls = []
    for ent in (note_res.get("entity_set"), legacy.get("entities")):
        if not isinstance(ent, dict):
            continue
        if isinstance(ent.get("urls"), list):
            urls.extend(u for u in ent["urls"] if isinstance(u, dict))
        if isinstance(ent.get("media"), list):
            for m in ent["media"]:
                if isinstance(m, dict) and m.get("url"):
                    media_urls.append(m["url"])

    if not tid and full_text is None:
        return None
    return {"text": full_text, "id": tid, "urls": urls, "media_urls": media_urls}


def _check_create_response(resp, text):
    """X'in gönderim yanıtını denetle; yayınlanan metin + gönderi kimliğini döndür."""
    if resp.status < 200 or resp.status >= 300:
        raise ApiRejected(f"X gönderimi reddetti (HTTP {resp.status}).")
    try:
        data = resp.json()
    except Exception:
        return None
    posted = _extract_tweet_from_response(data)
    # Gönderi gerçekten oluştuysa (tid/result varsa), tali GraphQL errors uyarısıyla
    # başarısız sayma; yalnızca sonuç yokken hata varsa reddet.
    if posted and posted.get("id"):
        return posted
    if isinstance(data, dict) and data.get("errors"):
        e0 = data["errors"][0]
        msg = e0.get("message") if isinstance(e0, dict) else str(e0)
        raise ApiRejected(f"X gönderimi reddetti: {str(msg)[:150]}")
    return posted


def _wait_button_enabled(btn, text, timeout=8.0):
    """Gönder butonunun görünür ve aktif olmasını bekle; pasif kalırsa sebebini hemen açıkla."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if btn.is_visible() and btn.is_enabled():
                return
        except Exception:
            pass
        time.sleep(0.2)
    if len(text) > LIMIT:
        raise ApiRejected(
            f"X bu mesajı kabul etmiyor: toplam {len(text)} karakter. "
            "Hesabın 280 karakterle sınırlıysa limit üstü mesaj yayınlanamaz.")
    raise RuntimeError("Gönder butonu aktifleşmedi (X editörü metni işlemedi).")


def _click_post(page, btn, text):
    """Butonun aktifleşmesini bekle ve tıkla; katman engellerse zorla/JS ile dene."""
    _wait_button_enabled(btn, text)
    try:
        btn.click(timeout=5000)
        return
    except PWTimeout:
        pass
    try:
        btn.click(timeout=4000, force=True)
        return
    except Exception:
        pass
    btn.evaluate("el => el.click()")


def _wait_posted(page):
    """Gönderimi doğrula: mesaj penceresinin kapanması veya onay baloncuğu."""
    btn = page.locator(SEL_DIALOG_POST).first
    toast = page.locator(SEL_TOAST).first
    for _ in range(125):  # ~25 sn
        try:
            if btn.count() == 0 or not btn.is_visible():
                return  # pencere kapandı = gönderildi
        except Exception:
            return
        try:
            if toast.count() > 0 and toast.is_visible():
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("X gönderimi onaylamadı (mesaj penceresi açık kaldı). "
                       "Bağlantı yavaşsa tekrar deneyin; sürerse hata mesajını iletin.")


def _modal_gone(page, box=None, btn=None, had_text=True):
    try:
        target = btn if btn is not None else page.locator(SEL_DIALOG_POST).first
        if target.count() == 0 or not target.is_visible():
            return True
        if box is not None and had_text:
            # Satır-içi composer gönderim sonrası görünür kalır ama kutu boşalır
            try:
                testid = target.get_attribute("data-testid")
            except Exception:
                testid = None
            if testid == "tweetButtonInline" and not target.is_enabled() and not _box_text(box).strip():
                return True
        return False
    except Exception:
        return True


def _is_create_request(req):
    if req.method != "POST":
        return False
    return bool(re.search(r"/(CreateTweet|CreateNoteTweet|CreatePost)(?:[/?#]|$)", req.url))


def _submit_and_confirm(page, box, btn, text, media_timeout=False):
    """Ctrl+Enter ile gönder; X'in onayını bekle.
    Dönüş: (posted_dict_veya_None, how) — how: confirmed / modal_closed / still_open.
    Ağ isteği izlenir: Ctrl+Enter isteği başlattığı an buton ASLA ikinci kez
    tıklanmaz (çift paylaşım yasağı). Yalnızca Ctrl+Enter 5 sn boyunca hiçbir
    gönderim isteği başlatmadıysa buton TEK KEZ tıklanır."""
    _wait_button_enabled(btn, text, timeout=(25.0 if media_timeout else 8.0))
    had_text = bool((text or "").strip() or media_timeout)

    started_reqs = []
    responses = []
    failed_reqs = []

    def on_request(req):
        if _is_create_request(req):
            started_reqs.append(req)

    def on_response(resp):
        if _is_create_request(resp.request):
            responses.append(resp)

    def on_failed(req):
        if _is_create_request(req):
            failed_reqs.append(req.failure or "request failed")

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_failed)
    try:
        page.bring_to_front()
        try:
            box.focus()
        except Exception:
            pass
        page.keyboard.press("Control+Enter")

        # 5 sn içinde gönderim isteğinin başlamasını veya pencerenin kapanmasını bekle
        trigger_deadline = time.time() + 5.0
        while time.time() < trigger_deadline:
            if responses:
                return _check_create_response(responses[0], text), "confirmed"
            if started_reqs or _modal_gone(page, box, btn, had_text):
                break
            time.sleep(0.15)

        # Ctrl+Enter hiçbir istek başlatmadıysa ve pencere hâlâ açıksa TEK KEZ butona bas
        if not started_reqs and not responses and not _modal_gone(page, box, btn, had_text):
            try:
                still_enabled = btn.is_enabled()
            except Exception:
                still_enabled = False
            if still_enabled:
                _click_post(page, btn, text)

        # Yanıtı bekle (en fazla 25 sn); istek zaten gittiyse asla tekrar gönderme
        resp_deadline = time.time() + 25.0
        modal_closed_at = None
        fail_seen_at = None
        while time.time() < resp_deadline:
            if responses:
                return _check_create_response(responses[0], text), "confirmed"
            if _modal_gone(page, box, btn, had_text):
                if modal_closed_at is None:
                    modal_closed_at = time.time()
                elif time.time() - modal_closed_at >= 3.0:
                    return None, "modal_closed"
            if failed_reqs and len(failed_reqs) >= max(1, len(started_reqs)):
                if fail_seen_at is None:
                    fail_seen_at = time.time()
                elif time.time() - fail_seen_at >= 1.5:
                    if _modal_gone(page, box, btn, had_text):
                        return None, "modal_closed"
                    raise RuntimeError(f"X gönderim isteği ağ hatası verdi: {failed_reqs[0]}")
            time.sleep(0.2)

        # Son bir kontrol: pencere kapandıysa gönderim büyük olasılıkla tamamlandı
        close_deadline = time.time() + 5.0
        while time.time() < close_deadline:
            if responses:
                return _check_create_response(responses[0], text), "confirmed"
            if _modal_gone(page, box, btn, had_text):
                return None, "modal_closed"
            time.sleep(0.3)
        return None, ("modal_closed" if _modal_gone(page, box, btn, had_text) else "still_open")
    finally:
        for ev, fn in (("request", on_request), ("response", on_response), ("requestfailed", on_failed)):
            try:
                page.remove_listener(ev, fn)
            except Exception:
                pass


def _find_tweet_article(page, status_id=None, timeout=15000):
    """Sayfadaki hedef gönderi kartını (article) bul; zincirde üst gönderiye çarpmaz."""
    page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=timeout)
    if status_id:
        for sel in (
            f'article[data-testid="tweet"]:has(a[href*="/status/{status_id}"] time)',
            f'article[data-testid="tweet"]:has(a[href*="/status/{status_id}"])',
        ):
            loc = page.locator(sel).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                pass
    return page.locator('article[data-testid="tweet"]').first


def _retract(page, tweet_id):
    """Yayımlanan gönderiyi kendi kalıcı bağlantısından açıp SİLER (geri çeker)."""
    try:
        page.goto(f"https://x.com/i/web/status/{tweet_id}", wait_until="domcontentloaded")
        time.sleep(2.5)
        art = _find_tweet_article(page, tweet_id, timeout=10000)
        art.locator('[data-testid="caret"]').first.click(timeout=5000)
        time.sleep(1)
        items = page.locator('[role="menuitem"]')
        for j in range(items.count()):
            label = items.nth(j).inner_text().strip().lower()
            if label.startswith("delete") or label.startswith("sil"):
                items.nth(j).click()
                time.sleep(1)
                page.locator('[data-testid="confirmationSheetConfirm"]').first.click(timeout=5000)
                time.sleep(1)
                return True
    except Exception:
        return False
    return False


def _profile_path(page):
    """Oturum açmış kullanıcının profil yolunu (/kullanici) al."""
    loc = page.locator('[data-testid="AppTabBar_Profile_Link"]').first
    try:
        if loc.count():
            href = loc.get_attribute("href")
            if href:
                return href
    except Exception:
        pass
    page.goto(HOME_URL, wait_until="domcontentloaded")
    loc = page.locator('[data-testid="AppTabBar_Profile_Link"]').first
    loc.wait_for(state="visible", timeout=10000)
    return loc.get_attribute("href")


def _check_tweet_articles(page, text, max_items=6, has_media=False, quoted_sid=None):
    """Mevcut sayfadaki gönderi kartlarında beklenen metni ara; uzunsa adayları kalıcı linkten doğrula."""
    try:
        page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=10000)
    except Exception:
        return False
    time.sleep(0.8)
    arts = page.locator('article[data-testid="tweet"]')
    count = min(arts.count(), max_items)
    exp_n = _norm(text)
    candidates = []
    for i in range(count):
        try:
            art = arts.nth(i)
            txt_loc = art.locator('[data-testid="tweetText"]').first
            if not txt_loc.count():
                continue
            t_raw = txt_loc.inner_text()
            if _published_matches(t_raw, text, has_media=has_media, quoted_sid=quoted_sid):
                return True
            show_more = art.locator('[data-testid="tweet-text-show-more-link"]').first
            has_more = bool(show_more.count())
            if has_more or len(exp_n) > 240:
                t_prefix = _norm(t_raw).rstrip(".…")
                probe = t_prefix[:min(len(t_prefix), 50)]
                if len(probe) >= 20 and (probe in exp_n or exp_n.startswith(probe[:25])):
                    href = art.locator('a[href*="/status/"]:has(time)').first.get_attribute("href")
                    if href:
                        candidates.append(href)
        except Exception:
            continue
    for href in candidates:
        try:
            url = href if href.startswith("http") else f"https://x.com{href}"
            m = re.search(r"/status(?:es)?/(\d+)", url)
            sid = m.group(1) if m else None
            page.goto(url, wait_until="domcontentloaded")
            focal = _find_tweet_article(page, sid, timeout=10000)
            full_loc = focal.locator('[data-testid="tweetText"]').first
            full_loc.wait_for(state="visible", timeout=8000)
            if _published_matches(full_loc.inner_text(), text, has_media=has_media, quoted_sid=quoted_sid):
                return True
        except Exception:
            continue
    return False


def _latest_post_has_media(page, max_items=3):
    try:
        page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=10000)
    except Exception:
        return False
    arts = page.locator('article[data-testid="tweet"]')
    for i in range(min(arts.count(), max_items)):
        try:
            if arts.nth(i).locator('[data-testid="tweetPhoto"]').count():
                return True
        except Exception:
            continue
    return False


def _post_exists(page, text, has_media=False, quoted_sid=None):
    """Gönderinin GERÇEKTEN yayımlanıp yayımlanmadığını profilin en üstünden doğrula.
    X gönderiyi profilde işlemesi birkaç saniye sürebilir -> üç tur bakılır."""
    try:
        prof = _profile_path(page)
        if not prof:
            return False
        has_text = bool((text or "").strip())
        for _ in range(3):
            page.goto(f"https://x.com{prof}", wait_until="domcontentloaded")
            if has_text and _check_tweet_articles(page, text, max_items=6,
                                                 has_media=has_media, quoted_sid=quoted_sid):
                return True
            if not has_text and has_media and _latest_post_has_media(page, max_items=3):
                return True
            time.sleep(3)
    except Exception:
        return False
    return False


def _dismiss_composer(page):
    """Açık mesaj penceresini YAYINLAMADAN temizle-kapat (en iyi çaba)."""
    try:
        box = page.locator(f'{SEL_DIALOG_TEXTAREA}, [data-testid="tweetTextarea_0"]').first
        if box.count():
            box.focus()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
    except Exception:
        pass
    try:
        close = page.locator('[data-testid="app-bar-close"]')
        if close.count():
            close.first.click(timeout=2000)
            time.sleep(0.5)
    except Exception:
        pass
    _dismiss_discard_dialog(page)


def _verify_composed(page, posted, text, log, how, has_media=False, quoted_sid=None):
    """X yanıtı yakalandıysa: yayınlanan içeriği beklenenle karşılaştır,
    bozuksa otomatik geri çek; pencere açıksa temizle."""
    body = posted.get("text") if posted else None
    if posted is None or body is None:
        tid = posted.get("id") if posted else None
        extra = f" (id: {tid})" if tid else " (içerik okunamadı)"
        log(f"X gönderim yanıtını doğruladı ({how}) ✓{extra}")
    elif not (text or "").strip() and has_media:
        tid = posted.get("id")
        extra = f" (id: {tid})" if tid else ""
        log(f"X görselli gönderiyi onayladı ({how}) ✓{extra}")
    else:
        if not _published_matches(body, text, posted.get("urls"),
                                  posted.get("media_urls"), has_media=has_media, quoted_sid=quoted_sid):
            tid = posted.get("id")
            if tid and _retract(page, tid):
                raise RuntimeError(
                    f"X mesajı bozuk yayımladı ama OTOMATİK GERİ ÇEKİLDİ. "
                    f"Yayınlanan: {body[:60]!r} — lütfen tekrar deneyin.")
            raise RuntimeError(
                f"DİKKAT: X mesajı bozuk yayımladı ve geri çekilemedi! "
                f"Yayınlanan: {body[:60]!r} — profilinizden elle silin.")
        log(f"X gönderimi onayladı ve içerik doğrulandı ({how}) ✓")
    time.sleep(1.2)
    try:
        if not _modal_gone(page):
            page.locator('[data-testid="app-bar-close"]').first.click(timeout=3000)
    except Exception:
        pass


def _attach_image(page, image_path, log):
    """Açık mesaj/yanıt penceresindeki fileInput üzerinden görseli yükler ve önizlemeyi bekler."""
    if not image_path or not os.path.isfile(image_path):
        raise RuntimeError(f"Seçilen görsel dosyası bulunamadı: {image_path}")
    log("Görsel gönderiye ekleniyor...")
    fi = None
    for sel in ('[role="dialog"] input[data-testid="fileInput"]', 'input[data-testid="fileInput"]'):
        loc = page.locator(sel).first
        try:
            if loc.count():
                fi = loc
                break
        except Exception:
            pass
    if fi is None:
        raise RuntimeError("X penceresinde görsel yükleme alanı bulunamadı.")
    fi.set_input_files(os.path.abspath(image_path))
    try:
        page.locator('[role="dialog"] [data-testid="attachments"], [data-testid="attachments"]').first.wait_for(
            state="visible", timeout=15000
        )
    except Exception as e:
        raise RuntimeError(f"X görseli pencereye yükleyemedi: {e}")
    time.sleep(0.8)


def _prepare_and_submit(page, open_fn, text, log, image_path=None, reset_fn=None,
                        fail_prefix="Metin kutuya yerleştirilemedi"):
    """Açılan mesaj/yanıt/alıntı penceresine metni ve varsa görseli koyar, TEK KEZ gönderir."""
    has_text = bool((text or "").strip())
    has_media = bool(image_path)
    last_err = None
    box = btn = None
    strat = "media-only"
    if has_text:
        for strat in ("paste", "exec", "type"):
            try:
                box, btn = open_fn()
                box.wait_for(state="visible", timeout=10000)
                _insert_with(page, box, text, strat)
                time.sleep(1.5)  # insansı bekleme + editör otursun
                if _norm(_box_text(box)) != _norm(text):
                    raise RuntimeError("kutu doğrulaması tutmadı")
                break
            except Exception as e:
                last_err = e
                log(f"Yerleştirme yöntemi '{strat}' başarısız: {e}")
                _dismiss_composer(page)
                if reset_fn:
                    reset_fn()
        else:
            raise RuntimeError(f"{fail_prefix} ({last_err}).")
    else:
        box, btn = open_fn()
        box.wait_for(state="visible", timeout=10000)

    if has_media:
        try:
            _attach_image(page, image_path, log)
        except Exception:
            _dismiss_composer(page)
            raise

    posted, how = _submit_and_confirm(page, box, btn, text, media_timeout=has_media)
    return posted, how, strat


def _try_send(page, text, log, image_path=None):
    """GÖNDER BAŞINA EN FAZLA BİR GÖNDERİM garantisi:
    * Yerleştirme stratejileri (paste/exec/type) yalnızca metni kutuya koymak
      içindir; yerleştirme başarısızsa gönderim HİÇ yapılmadan sıradaki denenir.
    * Metin yerleştiği an (varsa görsel yüklenip) TEK gönderim yapılır; sonucu sabırla doğrulanır.
    * Gönderim denendikten sonra ne olursa olsun OTOMATİK tekrar gönderilmez."""
    page.bring_to_front()
    has_media = bool(image_path)

    def _open_new():
        open_composer(page)
        return _get_composer(page)

    posted, how, strat = _prepare_and_submit(
        page, _open_new, text, log, image_path=image_path, fail_prefix="Metin kutuya yerleştirilemedi"
    )
    if how == "confirmed":
        _verify_composed(page, posted, text, log, strat, has_media=has_media)
        return
    if how == "modal_closed":
        # gönderim olmuş olabilir; sabırla kanıtla — ASLA tekrar gönderme
        if _post_exists(page, text, has_media=has_media):
            log("Gönderi profilinde doğrulandı ✓")
            return
        raise SubmitAttempted("Pencere kapandı ancak gönderi doğrulanamadı. "
                              "TEKRAR GÖNDERMEDEN önce profilini kontrol et (çift paylaşım olmasın).")
    raise SubmitAttempted("X gönderim isteği başlatmadı (pencere açık kaldı). "
                          "Tekrar denemek için Gönder'e tekrar bas.")


def do_send(page, text, log, image_path=None):
    """Tek gönderim garantisiyle gönderir. Gönderim bir kez denendikten sonra
    ne olursa olsun OTOMATİK tekrar yapılmaz; hatalar olduğu gibi yükseltilir."""
    try:
        _try_send(page, text, log, image_path=image_path)
    except ApiRejected as e:
        raise RuntimeError(str(e))
    except SubmitAttempted as e:
        raise RuntimeError(str(e))


# ---------------------------------------------------------------- arka plan işleri

def extract_status_id(link):
    """'https://x.com/kullanici/status/123...' biçimli linkten gönderi kimliğini al."""
    m = re.search(r"/status(?:es)?/(\d+)", link)
    return m.group(1) if m else None


def _do_like(tweet, log, quiet=False, pause=1.2):
    if tweet.locator('[data-testid="unlike"]').count():
        if not quiet:
            log("Bu gönderi zaten beğenilmiş — Like atlandı.")
        return False
    tweet.locator('[data-testid="like"]').first.click(timeout=8000)
    time.sleep(pause)
    if not quiet:
        log("Like ✓")
    return True


def _do_repost(page, tweet, log, quiet=False, pause=1.2):
    un = tweet.locator('[data-testid="unretweet"]')
    if un.count() and un.first.is_visible():
        if not quiet:
            log("Bu gönderi zaten repost edilmiş — Repost atlandı.")
        return False
    tweet.locator('[data-testid="retweet"]').first.click(timeout=8000)
    confirm = page.locator('[data-testid="retweetConfirm"]').first
    confirm.wait_for(state="visible", timeout=5000)
    confirm.click()
    time.sleep(pause)
    if not quiet:
        log("Repost ✓")
    return True


HASHTAG_MARK_TARGET = 30


def _extract_hash_words(tags_text):
    """Hashtag kutusundan yalnızca '#' ile başlayan benzersiz kelimeleri sırasıyla çıkarır."""
    found = re.findall(r"(?<!\S)#[^\s#,.;:!?()\[\]\"']+", tags_text or "")
    seen = set()
    out = []
    for tag in found:
        if len(tag) <= 1:
            continue
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def hashtag_search_url(tag):
    """Verilen hashtag için X canlı (En Son) arama adresini döndürür."""
    return f"https://x.com/search?q={urllib.parse.quote(tag)}&src=hashtag_click&f=live"


def _tweet_status_key(art):
    for sel in ('a[href*="/status/"]:has(time)', 'a[href*="/status/"]'):
        loc = art.locator(sel).first
        try:
            if loc.count():
                href = loc.get_attribute("href")
                sid = extract_status_id(href or "")
                if sid:
                    return f"id:{sid}"
        except Exception:
            pass
    try:
        t = art.locator('[data-testid="tweetText"]').first
        if t.count():
            txt = _norm(t.inner_text())[:80]
            if txt:
                return f"txt:{txt}"
    except Exception:
        pass
    return None


def _click_tweet_action_safe(page, art, fn):
    """Sanal listedeki karta odaklanıp işlemi uygular; üst sabit başlık engellerse kaydırıp dener."""
    try:
        art.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    try:
        return fn()
    except Exception:
        try:
            page.evaluate("() => window.scrollBy(0, -100)")
            time.sleep(0.25)
        except Exception:
            pass
        return fn()


def mark_hashtag_posts(page, tag, like=False, repost=False, log=print, target=HASHTAG_MARK_TARGET):
    """Hashtag sayfasındaki mesajlarda seçili Like ve/veya Repost işlemini en az target mesaja uygular."""
    if not like and not repost:
        raise RuntimeError(f"{tag} için en az bir işlem seç (Like ve/veya Repost).")
    page.bring_to_front()
    log(f"{tag} sayfası açılıyor...")
    page.goto(hashtag_search_url(tag), wait_until="domcontentloaded")
    try:
        page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=12000)
    except Exception:
        log(f"{tag} için mesaj bulunamadı.", error=True)
        return {"acted": 0, "skipped": 0, "seen": 0}
    time.sleep(1.0)

    seen = set()
    acted = 0
    skipped = 0
    idle_scrolls = 0
    consec_errs = 0
    max_seen = max(target * 4, 120)

    while acted < target and idle_scrolls < 4 and len(seen) < max_seen:
        arts = page.locator('article[data-testid="tweet"]')
        count = arts.count()
        new_in_pass = False
        for i in range(count):
            if acted >= target:
                break
            art = arts.nth(i)
            try:
                if art.locator('[data-testid="placementTracking"]').count():
                    continue
            except Exception:
                pass
            key = _tweet_status_key(art)
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            new_in_pass = True

            did_any = False
            try:
                if like:
                    if _click_tweet_action_safe(page, art, lambda a=art: _do_like(a, log, quiet=True, pause=0.35)):
                        did_any = True
                if repost:
                    if _click_tweet_action_safe(page, art, lambda a=art: _do_repost(page, a, log, quiet=True, pause=0.35)):
                        did_any = True
                consec_errs = 0
            except Exception as e:
                consec_errs += 1
                log(f"{tag} bir mesajda atlandı: {str(e)[:80]}")
                if consec_errs >= 5:
                    raise RuntimeError(f"{tag} işaretlenirken art arda hatalar oluştu: {e}")
                continue

            if did_any:
                acted += 1
                if acted % 5 == 0 or acted == target:
                    log(f"{tag}: {acted}/{target} mesaj işaretlendi...")
            else:
                skipped += 1
            time.sleep(0.25)

        if acted >= target:
            break
        if new_in_pass:
            idle_scrolls = 0
        else:
            idle_scrolls += 1
        try:
            page.evaluate("() => window.scrollBy(0, Math.max(700, Math.floor((window.innerHeight || 800) * 0.85)))")
        except Exception:
            break
        time.sleep(1.5 if not new_in_pass else 1.2)

    try:
        page.goto(HOME_URL, wait_until="domcontentloaded")
    except Exception:
        pass
    if acted >= target:
        log(f"{tag}: {acted} mesaj işaretlendi ✓" + (f" ({skipped} zaten işaretli atlandı)" if skipped else ""))
    else:
        log(f"{tag}: {acted} mesaj işaretlendi ✓ (sayfada {len(seen)} mesaj incelendi"
            + (f", {skipped} zaten işaretli" if skipped else "") + ")")
    return {"acted": acted, "skipped": skipped, "seen": len(seen)}


def mark_hashtag_plan(tag, like, repost, log, done, target=HASHTAG_MARK_TARGET):
    try:
        if not ensure_chrome(log):
            done(False)
            return
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = find_x_page(context)
            if not is_logged_in(page, timeout=3000):
                log("X'e giriş yapılmamış. Lütfen açılan Chrome penceresinde giriş yap, sonra tekrar dene.", error=True)
                done(False)
                return
            mark_hashtag_posts(page, tag, like=like, repost=repost, log=log, target=target)
            done(True)
    except Exception as e:
        traceback.print_exc()
        log(f"Hashtag işaretleme hatası: {e}", error=True)
        done(False)


def _open_url_in_chrome_or_browser(url, log=None, label="", on_page=None, fallback_url=None):
    """URL'yi CDP Chrome açıksa yeni sekmede, değilse varsayılan tarayıcıda aç."""
    dest = label or url
    if cdp_alive():
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                page.bring_to_front()
                page.goto(url, wait_until="domcontentloaded")
                if on_page is not None:
                    res = on_page(page)
                    if res:
                        return res
                if log:
                    log(f"{dest} açıldı.")
                return "chrome"
        except Exception as e:
            if log:
                log(f"Chrome sekmesi açılamadı ({e}); varsayılan tarayıcı deneniyor...")
    target = fallback_url or url
    if webbrowser.open(target):
        if log:
            log(f"{dest} varsayılan tarayıcıda açıldı.")
        return "browser"
    if log:
        log(f"{dest} açılamadı.", error=True)
    return None


def _open_x_message_screen(handle=AUTHOR_X_HANDLE, log=None):
    """@handle için X mesaj/DM ekranını aç (CDP Chrome açıksa yeni sekmede, değilse tarayıcıda)."""
    handle = (handle or AUTHOR_X_HANDLE).lstrip("@").strip()
    q_handle = urllib.parse.quote(handle, safe="")
    intent_url = f"https://x.com/intent/post?text=%40{q_handle}%20"
    profile_url = f"https://x.com/{q_handle}"

    def _route_dm_or_compose(page):
        dm_btn = page.locator('[data-testid="sendDMFromProfile"]').first
        try:
            page.locator(
                '[data-testid="sendDMFromProfile"], [data-testid="editProfileButton"]'
            ).first.wait_for(state="visible", timeout=3500)
        except Exception:
            pass
        if dm_btn.count() and dm_btn.is_visible():
            dm_btn.click(timeout=5000)
            if log:
                log(f"@{handle} için X mesaj (DM) ekranı açıldı.")
            return "dm"
        # Kendi profili veya DM kapalıysa doğrudan @handle etiketli mesaj yazma ekranına geç
        page.goto(intent_url, wait_until="domcontentloaded")
        if log:
            log(f"@{handle} için X mesaj yazma ekranı açıldı.")
        return "compose"

    return _open_url_in_chrome_or_browser(
        profile_url,
        log=log,
        label=f"@{handle} için X mesaj ekranı",
        on_page=_route_dm_or_compose,
        fallback_url=intent_url,
    )


def _open_youtube_channel(handle=AUTHOR_YT_HANDLE, log=None):
    """@handle YouTube kanalını aç (CDP Chrome açıksa yeni sekmede, değilse tarayıcıda)."""
    handle = (handle or AUTHOR_YT_HANDLE).lstrip("@").strip()
    q_handle = urllib.parse.quote(handle, safe="")
    channel_url = f"https://www.youtube.com/@{q_handle}"
    return _open_url_in_chrome_or_browser(
        channel_url,
        log=log,
        label=f"YouTube: @{handle} kanalı",
    )


def _do_bookmark(tweet, log):
    rm = tweet.locator('[data-testid="removeBookmark"]')
    if rm.count() and rm.first.is_visible():
        log("Bu gönderi zaten yer imlerine ekli — Bookmark atlandı.")
        return
    tweet.locator('[data-testid="bookmark"]').first.click(timeout=8000)
    time.sleep(1.2)
    log("Bookmark ✓")


def _reply_exists_on_profile(page, text, has_media=False):
    """Yanıt hedef sayfada sıralama yüzünden görünmüyorsa kullanıcının /with_replies sekmesinden doğrula."""
    try:
        prof = _profile_path(page)
        if not prof:
            return False
        page.goto(f"https://x.com{prof}/with_replies", wait_until="domcontentloaded")
        if (text or "").strip():
            return _check_tweet_articles(page, text, max_items=6, has_media=has_media)
        return bool(has_media and _latest_post_has_media(page, max_items=3))
    except Exception:
        return False


def _do_reply(page, tweet, sid, text, log, image_path=None):
    log("Yanıt penceresi açılıyor...")
    has_text = bool((text or "").strip())
    has_media = bool(image_path)
    r_state = {"tweet": tweet}

    def _open_reply_box():
        if not page.locator(SEL_DIALOG_TEXTAREA).first.is_visible():
            target = _find_tweet_article(page, sid, timeout=10000) if r_state["tweet"] is None else r_state["tweet"]
            target.locator('[data-testid="reply"]').first.click(timeout=8000)
            page.locator(SEL_DIALOG_TEXTAREA).first.wait_for(state="visible", timeout=10000)
        return _get_composer(page)

    posted, how, strat = _prepare_and_submit(
        page, _open_reply_box, text, log, image_path=image_path,
        reset_fn=lambda: r_state.update(tweet=None), fail_prefix="Yanıt metni yerleştirilemedi",
    )
    if how == "confirmed":
        _verify_composed(page, posted, text, log, f"reply/{strat}", has_media=has_media)
        log("Reply ✓")
        return
    if how == "modal_closed":
        # pencere kapandı: yanıt büyük olasılıkla gitti. Önce mevcut sayfaya, ardından
        # sıralama/kısaltma nedeniyle bulunmazsa kullanıcının Yanıtlar sekmesine bak.
        for wait in (2, 4):
            time.sleep(wait)
            if has_text and _check_tweet_articles(page, text, max_items=15, has_media=has_media):
                log("Reply ✓ (yanıt sayfada doğrulandı)")
                return
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
        if _reply_exists_on_profile(page, text, has_media=has_media):
            log("Reply ✓ (yanıt profilinde doğrulandı)")
            return
        raise RuntimeError("Yanıt penceresi kapandı ama yanıt sayfada doğrulanamadı "
                           "(profil yanıtlarında da bulunamadı). Profilinden kontrol et.")
    raise RuntimeError("X yanıt isteği başlatmadı (pencere açık kaldı). Tekrar deneyin.")


_QUOTE_MENU_SELECTORS = (
    '[role="menuitem"] a[href="/compose/post"]',
    'a[role="menuitem"][href="/compose/post"]',
    '[role="menuitem"]:has(a[href="/compose/post"])',
    '[role="menuitem"]:has-text("Quote")',
    '[role="menuitem"]:has-text("Alıntı")',
)


def _do_quote(page, tweet, sid, text, log, image_path=None):
    log("Alıntı (Quote) penceresi açılıyor...")
    has_media = bool(image_path)
    q_state = {"tweet": tweet}

    def _open_quote_box():
        dlg = page.locator(SEL_DIALOG_TEXTAREA).first
        dlg_open = False
        try:
            dlg_open = bool(dlg.count() and dlg.is_visible())
        except Exception:
            dlg_open = False
        if not dlg_open and "/compose/post" not in (page.url or ""):
            if f"/status/{sid}" not in (page.url or ""):
                page.goto(f"https://x.com/i/web/status/{sid}", wait_until="domcontentloaded")
                q_state["tweet"] = None
            target = q_state["tweet"] if q_state["tweet"] is not None else _find_tweet_article(page, sid, timeout=10000)
            rt_btn = None
            for r_sel in ('[data-testid="retweet"]', '[data-testid="unretweet"]'):
                cand = target.locator(r_sel).first
                try:
                    if cand.count() and cand.is_visible():
                        rt_btn = cand
                        break
                except Exception:
                    pass
            if rt_btn is None:
                raise RuntimeError("Alıntılama (Quote) için Repost/Quote menü butonu bulunamadı.")
            rt_btn.click(timeout=8000)
            combined_q = ", ".join(_QUOTE_MENU_SELECTORS)
            page.locator(combined_q).first.wait_for(state="visible", timeout=6000)
            q_item = None
            for q_sel in _QUOTE_MENU_SELECTORS:
                loc = page.locator(q_sel).first
                try:
                    if loc.count() and loc.is_visible():
                        q_item = loc
                        break
                except Exception:
                    pass
            if q_item is None:
                raise RuntimeError("Açılan menüde Quote (Alıntıla) seçeneği bulunamadı.")
            q_item.click(timeout=5000)
            page.locator(f'{SEL_DIALOG_TEXTAREA}, [data-testid="tweetTextarea_0"]').first.wait_for(
                state="visible", timeout=10000
            )
        return _get_composer(page)

    posted, how, strat = _prepare_and_submit(
        page, _open_quote_box, text, log, image_path=image_path,
        reset_fn=lambda: q_state.update(tweet=None), fail_prefix="Alıntı metni yerleştirilemedi",
    )
    if how == "confirmed":
        _verify_composed(page, posted, text, log, f"quote/{strat}", has_media=has_media, quoted_sid=sid)
        log("Quote ✓")
        return
    if how == "modal_closed":
        if _post_exists(page, text, has_media=has_media, quoted_sid=sid):
            log("Quote ✓ (alıntı profilinde doğrulandı)")
            return
        raise RuntimeError("Alıntı penceresi kapandı ama alıntı profilde doğrulanamadı. "
                           "TEKRAR GÖNDERMEDEN önce profilini kontrol et.")
    raise RuntimeError("X alıntı isteği başlatmadı (pencere açık kaldı). Tekrar deneyin.")


def do_link_actions(page, plan, log):
    """Linkteki gönderiye seçilen işlemleri uygula: Like / Bookmark / Repost / Reply / Quote."""
    sid = extract_status_id(plan["link"])
    if not sid:
        raise RuntimeError("Linkten gönderi kimliği çözülemedi. Örnek biçim: "
                           "https://x.com/kullanici/status/1234567890123456789")
    page.bring_to_front()
    log("İşlem yapılacak gönderi açılıyor...")
    page.goto(f"https://x.com/i/web/status/{sid}", wait_until="domcontentloaded")
    tweet = _find_tweet_article(page, sid, timeout=15000)
    time.sleep(1)
    if plan.get("like"):
        _do_like(tweet, log)
    if plan.get("bookmark"):
        _do_bookmark(tweet, log)
    if plan.get("repost"):
        _do_repost(page, tweet, log)
    if plan.get("reply"):
        _do_reply(page, tweet, sid, plan["text"], log, image_path=plan.get("image"))
        track_counter(COUNTER_POST)
    if plan.get("quote"):
        _do_quote(page, tweet, sid, plan["text"], log, image_path=plan.get("image"))
        track_counter(COUNTER_POST)
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded")
    except Exception:
        pass


def send_plan(plan, log, done):
    """Planı sırayla uygula: (yeni gönderi) + (link işlemleri: Like/Bookmark/Repost/Reply/Quote)."""
    try:
        if not ensure_chrome(log):
            done(False)
            return
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = find_x_page(context)
            if not is_logged_in(page, timeout=3000):
                log("X'e giriş yapılmamış. Lütfen açılan Chrome penceresinde giriş yap, sonra tekrar dene.", error=True)
                done(False)
                return
            img = plan.get("image") or None
            if plan.get("post_new"):
                log("Yeni gönderi atılıyor...")
                do_send(page, plan["text"], log, image_path=img)
                track_counter(COUNTER_POST)
            if plan.get("do_link") and plan.get("link"):
                do_link_actions(page, plan, log)
            log("Tüm işlemler tamam ✓")
            done(True)
    except ApiRejected as e:
        log(f"Hata: {e}", error=True)
        done(False)
    except Exception as e:
        traceback.print_exc()
        log(f"Hata: {e}", error=True)
        done(False)


# ---------------------------------------------------------------- arayüz temaları

_THEMES = {
    "light": {
        "bg": "#f1f5f9",
        "sash": "#cbd5e1",
        "card": "#ffffff",
        "card_border": "#e2e8f0",
        "sub": "#f8fafc",
        "input_border": "#cbd5e1",
        "pill": "#f1f5f9",
        "fg": "#0f172a",
        "muted": "#64748b",
        "primary": "#1d9bf0",
        "primary_hover": "#1a8cd8",
        "emerald": "#059669",
        "emerald_hover": "#047857",
        "violet": "#6d4fc2",
        "violet_hover": "#5b3fb3",
        "teal": "#0f766e",
        "teal_hover": "#0d5f58",
        "danger": "#e0245e",
        "danger_bg": "#ffe4e6",
        "ok": "#16a34a",
        "ok_bg": "#dcfce7",
        "ok_fg": "#166534",
        "warn_bg": "#fef3c7",
        "warn_fg": "#92400e",
        "over_bg": "#ffd6d6",
        "over_fg": "#e0245e",
        "btn_sec_bg": "#eef2f6",
        "btn_sec_fg": "#1e293b",
        "btn_sec_hover": "#e2e8f0",
        "meter_track": "#e2e8f0",
        "meter_low": "#38bdf8",
        "meter_idle": "#94a3b8",
        "link_x": "#1d9bf0",
        "link_yt": "#d93025",
        "chk_select": "#ffffff",
        "ring_track": "#e2e8f0",
    },
    "dark": {
        "bg": "#0b1120",
        "sash": "#1e293b",
        "card": "#111827",
        "card_border": "#1f2937",
        "sub": "#0f172a",
        "input_border": "#334155",
        "pill": "#1e293b",
        "fg": "#f1f5f9",
        "muted": "#94a3b8",
        "primary": "#1d9bf0",
        "primary_hover": "#38bdf8",
        "emerald": "#10b981",
        "emerald_hover": "#059669",
        "violet": "#7c5ce0",
        "violet_hover": "#6d4fc2",
        "teal": "#0d9488",
        "teal_hover": "#0f766e",
        "danger": "#f43f5e",
        "danger_bg": "#4c0519",
        "ok": "#22c55e",
        "ok_bg": "#064e3b",
        "ok_fg": "#86efac",
        "warn_bg": "#451a03",
        "warn_fg": "#fcd34d",
        "over_bg": "#4c0519",
        "over_fg": "#fda4af",
        "btn_sec_bg": "#1e293b",
        "btn_sec_fg": "#e2e8f0",
        "btn_sec_hover": "#334155",
        "meter_track": "#0f172a",
        "meter_low": "#38bdf8",
        "meter_idle": "#475569",
        "link_x": "#38bdf8",
        "link_yt": "#f87171",
        "chk_select": "#1e293b",
        "ring_track": "#334155",
    },
}


# ---------------------------------------------------------------- arayüz

class XPoster:
    def __init__(self, root):
        self.root = root
        root.title("X Poster")
        root.geometry("1040x680")
        root.minsize(880, 600)

        self.q = queue.Queue()
        self.busy = False
        self.gen_busy = False
        self.img_busy = False
        self.stt_state = "idle"
        self._stt_cancel = False
        self._stt_accept_text = False
        self._stt_run_id = 0
        self._stt_perm_granted = False   # Her uygulama açılışında arayüzden temiz izin ister
        self._stt_device_index = None
        self._stt_devices = []
        self._stt_perm_win = None
        self.stt_controller = NativeSTTController(emit_cb=self._on_stt_event)
        self.theme = "light"
        self._t_items = []
        self._conn_state = "connecting"
        self._status_err = False
        self._last_meter = (0.0, 0.0012, False, False)
        self._char_count = 0
        self.used_angles = []
        self.used_focuses = []
        self.used_img_styles = []
        self.used_img_focuses = []
        self.recent_outputs = []
        self.ht_vars = {}
        self._ht_pending_prefs = {}
        self._ht_rendered_tags = None
        self._ht_mark_btns = []
        self.image_path = ""
        self.image_meta = ""
        self._thumb_photo = None
        self._preview_win = None
        self.last_send_sig = None
        self.last_send_time = 0.0
        self._last_link_clicks = {}
        self._resend_armed = False
        self._loaded = False   # Kritik: state yüklenmeden _save_state YAZMAZ (boşaltma bug'ı)
        self._login_done = threading.Event()
        threading.Thread(target=_serve_yz, daemon=True).start()

        def reg(w, role):
            self._t_items.append((w, role))
            return w

        def make_card(parent, padx=10, pady=8):
            return reg(tk.Frame(parent, highlightthickness=1, bd=0, padx=padx, pady=pady), "card")

        # --- Üst Tek-Sayfa Başlık Şeridi
        header_card = make_card(root, padx=12, pady=6)
        header_card.pack(side="top", fill="x", padx=14, pady=(10, 4))
        hdr_left = reg(tk.Frame(header_card), "card_plain")
        hdr_left.pack(side="left")
        reg(tk.Label(hdr_left, text="𝕏", font=("Segoe UI", 10, "bold"), padx=7, pady=1), "badge_primary").pack(side="left")
        reg(tk.Label(hdr_left, text="X Poster", font=("Segoe UI", 11, "bold")), "lbl").pack(side="left", padx=(8, 6))
        reg(tk.Label(hdr_left, text="Tek Sayfa Stüdyo", font=("Segoe UI", 8), padx=7, pady=2), "pill_muted").pack(side="left")

        hdr_right = reg(tk.Frame(header_card), "card_plain")
        hdr_right.pack(side="right")
        self.var_xuy = tk.BooleanVar(value=True)
        self.xuy_chk = reg(
            tk.Checkbutton(
                hdr_right, text="X-UY (≤ 280 krk)", variable=self.var_xuy,
                command=self.update_count, font=("Segoe UI", 8, "bold"),
                padx=8, pady=2, bd=0, highlightthickness=1, cursor="hand2",
            ),
            "chk_pill",
        )
        self.xuy_chk.pack(side="left", padx=(0, 8))
        self.theme_btn = reg(
            tk.Button(
                hdr_right, text="🌙 Koyu", command=self.toggle_theme,
                relief="flat", bd=0, highlightthickness=1,
                font=("Segoe UI", 8, "bold"), cursor="hand2", padx=9, pady=2,
            ),
            "btn_sec",
        )
        self.theme_btn.pack(side="left", padx=(0, 8))
        self.conn_pill = tk.Label(hdr_right, text="● Chrome bağlanıyor...", font=("Segoe UI", 8, "bold"), padx=8, pady=2)
        self.conn_pill.pack(side="left")

        # Alt sabit şerit ÖNCE side="bottom" ile yerleştirilir -> bölmeler oynatılsa da
        # Gönder / Durum / Sağ alt profil linkleri asla ekrandan taşmaz.
        bottom_wrap = reg(tk.Frame(root), "bg")
        bottom_wrap.pack(side="bottom", fill="x", padx=14, pady=(4, 10))
        bottom_card = make_card(bottom_wrap, padx=12, pady=7)
        bottom_card.pack(fill="x")

        bottom = reg(tk.Frame(bottom_card), "card_plain")
        bottom.pack(fill="x")
        reg(tk.Label(bottom, text="Ctrl+Enter ile hızlı gönder", font=("Segoe UI", 8)), "muted").pack(side="left")
        self.send_btn = reg(
            tk.Button(
                bottom, text="Gönder ↗", width=15, command=self.on_send,
                relief="flat", bd=0, font=("Segoe UI", 10, "bold"),
                cursor="hand2", pady=3, state="disabled",
            ),
            "btn_primary",
        )
        self.send_btn.pack(side="right")

        status_row = reg(tk.Frame(bottom_card), "card_plain")
        status_row.pack(fill="x", pady=(4, 0))
        self.status = reg(
            tk.Label(
                status_row, text="Chrome'a bağlanılıyor...", anchor="w", justify="left",
                font=("Segoe UI", 9), wraplength=580,
            ),
            "muted",
        )
        self.status.pack(side="left", fill="x", expand=True)
        links_box = reg(tk.Frame(status_row), "card_plain")
        links_box.pack(side="right", anchor="se", padx=(10, 0))
        link_specs = (
            ("author_link", f"x: @{AUTHOR_X_HANDLE}", "link_x", self.on_open_author_x),
            ("yt_link", f"YouTube: @{AUTHOR_YT_HANDLE}", "link_yt", self.on_open_youtube),
        )
        for idx, (attr, text, role, handler) in enumerate(link_specs):
            if idx:
                reg(tk.Label(links_box, text="|", font=("Segoe UI", 8)), "muted").pack(side="left", padx=6)
            lbl = reg(tk.Label(links_box, text=text, font=("Segoe UI", 8, "underline"), cursor="hand2"), role)
            lbl.pack(side="left")
            lbl.bind("<Button-1>", handler)
            setattr(self, attr, lbl)
        bottom_card.bind(
            "<Configure>",
            lambda e: self.status.config(
                wraplength=max(240, e.width - max(150, links_box.winfo_reqwidth() + 44))
            ),
        )

        # Ana yatay bölme: Sol = Mesaj / Hashtag / Konu, Sağ = Üretim & İşlemler
        self.main_pane = reg(
            tk.PanedWindow(
                root, orient="horizontal", sashwidth=7, sashpad=2,
                showhandle=False, sashrelief="flat", bd=0,
            ),
            "sash",
        )
        self.main_pane.pack(fill="both", expand=True, padx=14, pady=(2, 2))

        self._saved_sashes = None
        self.editor_pane = reg(
            tk.PanedWindow(
                self.main_pane, orient="vertical", sashwidth=7, sashpad=2,
                showhandle=False, sashrelief="flat", bd=0,
            ),
            "sash",
        )

        # 1) Mesaj Kartı + Alt Mikrofon Çubuğu
        pane_msg = make_card(self.editor_pane, padx=10, pady=5)
        msg_hdr = reg(tk.Frame(pane_msg), "card_plain")
        msg_hdr.pack(fill="x", pady=(0, 2))
        reg(tk.Label(msg_hdr, text="Ne paylaşmak istersin?", font=("Segoe UI", 10, "bold")), "lbl").pack(side="left")
        msg_hdr_r = reg(tk.Frame(msg_hdr), "card_plain")
        msg_hdr_r.pack(side="right")
        self.clear_msg_btn = reg(
            tk.Button(
                msg_hdr_r, text="Temizle", command=self._on_clear_message,
                relief="flat", bd=0, highlightthickness=1, font=("Segoe UI", 8), cursor="hand2", padx=7, pady=1,
            ),
            "btn_sec",
        )
        self.clear_msg_btn.pack(side="left", padx=(0, 8))
        self._char_ring = tk.Canvas(msg_hdr_r, width=18, height=18, highlightthickness=0, bd=0)
        self._char_ring.pack(side="left", padx=(0, 5))
        self._ring_bg_id = self._char_ring.create_oval(2, 2, 16, 16, width=2)
        self._ring_arc_id = self._char_ring.create_arc(2, 2, 16, 16, start=90, extent=0, style="arc", width=2)
        self.counter = reg(tk.Label(msg_hdr_r, text=f"0/{LIMIT}", font=("Segoe UI", 9, "bold"), padx=7, pady=1), "pill_muted")
        self.counter.pack(side="left")

        # Her zaman görünür mikrofon seçici şeridi en altta -> istenildiği an değiştirilebilir
        mic_dev_bar = reg(tk.Frame(pane_msg, highlightthickness=1, bd=0, padx=6, pady=1), "pill")
        mic_dev_bar.pack(side="bottom", fill="x", pady=(2, 0))
        reg(tk.Label(mic_dev_bar, text="🎙 Mikrofon:", font=("Segoe UI", 8)), "pill_muted").pack(side="left")
        self.var_stt_dev = tk.StringVar(value="Mikrofonlar yükleniyor...")
        self.mic_dev_menu = reg(
            tk.OptionMenu(mic_dev_bar, self.var_stt_dev, "Mikrofonlar yükleniyor..."),
            "opt",
        )
        self.mic_dev_menu.config(font=("Segoe UI", 8), relief="flat", highlightthickness=1, bd=0, pady=0, anchor="w")
        self.mic_dev_menu.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.mic_refresh_btn = reg(
            tk.Button(
                mic_dev_bar, text="↻ Yenile", command=self._refresh_stt_devices,
                relief="flat", bd=0, highlightthickness=1, font=("Segoe UI", 8), cursor="hand2", padx=6, pady=0,
            ),
            "btn_sec",
        )
        self.mic_refresh_btn.pack(side="right")

        # Mikrofon şeridi side="bottom" ile yerleşir -> bölme küçültülse de gizlenmez.
        mic_bar = reg(tk.Frame(pane_msg, highlightthickness=1, bd=0, padx=6, pady=2), "pill")
        mic_bar.pack(side="bottom", fill="x", pady=(3, 0))
        self.mic_btn = tk.Button(
            mic_bar, text="🎤 Sesle Yaz", command=self.on_stt_toggle,
            relief="flat", bd=0, font=("Segoe UI", 9, "bold"), cursor="hand2", padx=9, pady=1,
        )
        self.mic_btn.pack(side="left")
        self.var_stt_sens = tk.StringVar(value="Normal")
        self.mic_sens = reg(
            tk.OptionMenu(
                mic_bar, self.var_stt_sens, *_STT_SENS_LABELS.keys(),
                command=self._on_stt_sens_change,
            ),
            "opt",
        )
        self.mic_sens.config(font=("Segoe UI", 8), relief="flat", highlightthickness=1, bd=0, pady=1)
        self.mic_sens.pack(side="left", padx=(6, 0))
        self.mic_meter = tk.Canvas(mic_bar, width=96, height=14, highlightthickness=1, bd=0)
        self.mic_meter.pack(side="left", padx=(6, 0))
        self._meter_fill = self.mic_meter.create_rectangle(0, 0, 0, 14, fill="#94a3b8", width=0)
        self._meter_thr = self.mic_meter.create_line(-10, 0, -10, 14, fill="#dc2626", width=2)
        self.mic_status = reg(
            tk.Label(mic_bar, text="Türkçe STT • tıkla ve konuş", anchor="w", font=("Segoe UI", 8)),
            "pill_muted",
        )
        self.mic_status.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.text = reg(
            scrolledtext.ScrolledText(
                pane_msg, height=4, wrap="word", font=("Segoe UI", 11),
                undo=True, relief="flat", bd=0, highlightthickness=1, padx=6, pady=4,
            ),
            "text",
        )
        self.text.pack(fill="both", expand=True)
        self.text.bind("<KeyRelease>", self.update_count)
        self.text.bind("<<Paste>>", lambda e: self.root.after_idle(self.update_count))
        self.text.bind("<FocusOut>", self.update_count)
        self.text.bind("<Control-Return>", lambda e: (self.on_send(), "break")[1])

        # 2) Hashtag Kartı
        pane_tags = make_card(self.editor_pane, padx=10, pady=7)
        tags_hdr = reg(tk.Frame(pane_tags), "card_plain")
        tags_hdr.pack(fill="x", pady=(0, 4))
        reg(tk.Label(tags_hdr, text="Hashtag'ler", font=("Segoe UI", 9, "bold")), "lbl").pack(side="left")
        reg(tk.Label(tags_hdr, text="Her mesajın altına eklenir", font=("Segoe UI", 8)), "muted").pack(side="right")
        self.tags = reg(
            scrolledtext.ScrolledText(
                pane_tags, height=3, wrap="word", font=("Segoe UI", 10),
                undo=True, relief="flat", bd=0, highlightthickness=1, padx=6, pady=4,
            ),
            "text",
        )
        self.tags.pack(fill="both", expand=True)
        self.tags.bind("<KeyRelease>", self.update_count)
        self.tags.bind("<<Paste>>", lambda e: self.root.after_idle(self.update_count))
        self.tags.bind("<FocusOut>", self._on_tags_focus_out)
        try:
            if os.path.exists(HASHTAGS_FILE):
                with open(HASHTAGS_FILE, "r", encoding="utf-8") as f:
                    saved = f.read().strip()
                if saved:
                    self.tags.insert("1.0", saved)
        except Exception:
            pass

        # 3) Konu Kartı
        pane_topic = make_card(self.editor_pane, padx=10, pady=7)
        topic_hdr = reg(tk.Frame(pane_topic), "card_plain")
        topic_hdr.pack(fill="x", pady=(0, 4))
        reg(tk.Label(topic_hdr, text="Konu (YZ Mesaj Üretimi)", font=("Segoe UI", 9, "bold")), "lbl").pack(side="left")
        reg(tk.Label(topic_hdr, text="Otomatik kaydedilir", font=("Segoe UI", 8)), "muted").pack(side="right")
        self.topic = reg(
            scrolledtext.ScrolledText(
                pane_topic, height=3, wrap="word", font=("Segoe UI", 10),
                undo=True, relief="flat", bd=0, highlightthickness=1, padx=6, pady=4,
            ),
            "text",
        )
        self.topic.pack(fill="both", expand=True)
        self.topic.bind("<KeyRelease>", lambda e: self._save_state())
        self.topic.bind("<<Paste>>", lambda e: self.root.after_idle(self._save_state))
        self.topic.bind("<FocusOut>", lambda e: self._save_state())

        self.editor_pane.add(pane_msg, minsize=96, stretch="always")
        self.editor_pane.add(pane_tags, minsize=68, stretch="always")
        self.editor_pane.add(pane_topic, minsize=68, stretch="always")
        self.editor_pane.bind("<ButtonRelease-1>", lambda e: self.root.after_idle(self._save_state))

        # --- SAĞ SÜTUN (Tek bakışta tüm araçlar: YZ + Tek-Satır Bulut + İşlemler & Görsel + Hashtag İşaretleme)
        right_col = reg(tk.Frame(self.main_pane, padx=2), "bg")

        # Kart 1: YZ Mesaj Üretimi + Tek Satır Bulut API
        yzbox = make_card(right_col, padx=10, pady=8)
        yzbox.pack(fill="x", pady=(0, 6))
        yzhdr = reg(tk.Frame(yzbox), "card_plain")
        yzhdr.pack(fill="x", pady=(0, 5))
        reg(tk.Label(yzhdr, text="YZ Mesaj Üretimi", font=("Segoe UI", 9, "bold")), "lbl").pack(side="left")
        self.var_temp = tk.DoubleVar(value=1.0)
        trow = reg(tk.Frame(yzhdr), "card_plain")
        trow.pack(side="right")
        reg(tk.Label(trow, text="Çeşitlilik:", font=("Segoe UI", 8)), "muted").pack(side="left")
        self.temp_scale = reg(
            tk.Scale(
                trow, from_=0.3, to=1.3, resolution=0.1, orient="horizontal",
                variable=self.var_temp, showvalue=False, length=100,
                sliderlength=12, width=8, highlightthickness=0, bd=0,
                command=self._on_temp_change,
            ),
            "scale",
        )
        self.temp_scale.pack(side="left", padx=(4, 4))
        self.temp_val_lbl = reg(tk.Label(trow, text="1.0", font=("Segoe UI", 8, "bold"), padx=6, pady=1), "pill_lbl")
        self.temp_val_lbl.pack(side="left")

        yzbtns = reg(tk.Frame(yzbox), "card_plain")
        yzbtns.pack(fill="x")
        yzbtns.grid_columnconfigure(0, weight=1)
        yzbtns.grid_columnconfigure(1, weight=1)
        self.yz_btn = reg(
            tk.Button(
                yzbtns, text="✦ WebGPU Mesaj Üret", command=self.on_yz,
                relief="flat", bd=0, font=("Segoe UI", 9, "bold"), cursor="hand2", pady=4,
            ),
            "btn_emerald",
        )
        self.yz_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.cloud_btn = reg(
            tk.Button(
                yzbtns, text="⚡ Bulut Model Üret", command=self.on_cloud,
                relief="flat", bd=0, font=("Segoe UI", 9, "bold"), cursor="hand2", pady=4,
            ),
            "btn_violet",
        )
        self.cloud_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        cloud_grid = reg(tk.Frame(yzbox), "card_plain")
        cloud_grid.pack(fill="x", pady=(6, 0))
        cloud_grid.grid_columnconfigure(0, weight=5)
        cloud_grid.grid_columnconfigure(1, weight=4)
        cloud_grid.grid_columnconfigure(2, weight=3)
        reg(tk.Label(cloud_grid, text="Base URL (OpenAI/OpenRouter)", font=("Segoe UI", 8)), "muted").grid(row=0, column=0, sticky="w", padx=(0, 5))
        reg(tk.Label(cloud_grid, text="Model", font=("Segoe UI", 8)), "muted").grid(row=0, column=1, sticky="w", padx=(0, 5))
        reg(tk.Label(cloud_grid, text="API Key", font=("Segoe UI", 8)), "muted").grid(row=0, column=2, sticky="w")
        self.cloud_url = reg(tk.Entry(cloud_grid, font=("Segoe UI", 9), relief="flat", bd=0, highlightthickness=1), "entry")
        self.cloud_url.grid(row=1, column=0, sticky="ew", padx=(0, 5), ipady=3)
        self.cloud_model = reg(tk.Entry(cloud_grid, font=("Segoe UI", 9), relief="flat", bd=0, highlightthickness=1), "entry")
        self.cloud_model.grid(row=1, column=1, sticky="ew", padx=(0, 5), ipady=3)
        self.cloud_key = reg(tk.Entry(cloud_grid, show="•", font=("Segoe UI", 9), relief="flat", bd=0, highlightthickness=1), "entry")
        self.cloud_key.grid(row=1, column=2, sticky="ew", ipady=3)
        for w in (self.cloud_url, self.cloud_key, self.cloud_model):
            w.bind("<KeyRelease>", lambda e: self._save_state())
            w.bind("<<Paste>>", lambda e: self.root.after_idle(self._save_state))
            w.bind("<FocusOut>", lambda e: self._save_state())

        # Kart 2: İşlemler & Görsel Ekleme
        self.ops_frame = make_card(right_col, padx=10, pady=8)
        self.ops_frame.pack(fill="x")
        opshdr = reg(tk.Frame(self.ops_frame), "card_plain")
        opshdr.pack(fill="x", pady=(0, 4))
        reg(tk.Label(opshdr, text="İşlemler & Medya", font=("Segoe UI", 9, "bold")), "lbl").pack(side="left")

        linkrow = reg(tk.Frame(self.ops_frame), "card_plain")
        linkrow.pack(fill="x")
        self.var_post = tk.BooleanVar(value=True)
        reg(
            tk.Checkbutton(
                linkrow, text="Yeni Gönderi", variable=self.var_post,
                command=self.update_count, font=("Segoe UI", 9, "bold"), cursor="hand2",
            ),
            "chk",
        ).pack(side="left")
        reg(tk.Label(linkrow, text="|", font=("Segoe UI", 8)), "muted").pack(side="left", padx=4)
        self.var_link = tk.BooleanVar(value=False)
        reg(
            tk.Checkbutton(
                linkrow, text="Link:", variable=self.var_link,
                command=self.toggle_link, font=("Segoe UI", 9), cursor="hand2",
            ),
            "chk",
        ).pack(side="left")
        self.link_entry = reg(tk.Entry(linkrow, font=("Segoe UI", 9), relief="flat", bd=0, highlightthickness=1), "entry")
        self.link_entry.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=3)
        self.link_entry.bind("<KeyRelease>", self.update_count)
        self.link_entry.bind("<<Paste>>", lambda e: self.root.after_idle(self.update_count))

        acts = reg(tk.Frame(self.ops_frame), "card_plain")
        acts.pack(fill="x", pady=(6, 0))
        self.var_reply = tk.BooleanVar(value=True)
        self.var_quote = tk.BooleanVar(value=False)
        self.var_like = tk.BooleanVar(value=False)
        self.var_repost = tk.BooleanVar(value=False)
        self.var_bookmark = tk.BooleanVar(value=False)
        chip_specs = (
            ("ck_reply", "Reply", self.var_reply),
            ("ck_quote", "Quote", self.var_quote),
            ("ck_like", "Like", self.var_like),
            ("ck_repost", "Repost", self.var_repost),
            ("ck_bookmark", "Bookmark", self.var_bookmark),
        )
        self._action_chips = []
        for idx, (attr, text, var) in enumerate(chip_specs):
            ck = tk.Checkbutton(
                acts, text=text, variable=var, indicatoron=False,
                command=self._on_chip_toggle, relief="flat", bd=0,
                highlightthickness=1, padx=9, pady=2,
                font=("Segoe UI", 8, "bold"), cursor="hand2",
            )
            ck.pack(side="left", padx=(0 if idx == 0 else 5, 0))
            setattr(self, attr, ck)
            self._action_chips.append((ck, var))

        reg(tk.Frame(self.ops_frame, height=1), "divider").pack(fill="x", pady=(7, 6))

        imgbox = reg(tk.Frame(self.ops_frame), "card_plain")
        imgbox.pack(fill="x")
        imgrow = reg(tk.Frame(imgbox), "card_plain")
        imgrow.pack(fill="x")
        self.var_img = tk.BooleanVar(value=False)
        reg(
            tk.Checkbutton(
                imgrow, text="Resim Ekle", variable=self.var_img,
                command=self.toggle_img, font=("Segoe UI", 9, "bold"), cursor="hand2",
            ),
            "chk",
        ).pack(side="left")
        self.img_pick_btn = reg(
            tk.Button(
                imgrow, text="Dosya Seç...", command=self.on_pick_image,
                relief="flat", bd=0, highlightthickness=1, font=("Segoe UI", 8, "bold"), cursor="hand2", padx=8, pady=2,
            ),
            "btn_sec",
        )
        self.img_pick_btn.pack(side="left", padx=(8, 4))
        self.img_ai_btn = reg(
            tk.Button(
                imgrow, text="✦ YZ Resim Üret", command=self.on_gen_image,
                relief="flat", bd=0, font=("Segoe UI", 8, "bold"), cursor="hand2", padx=9, pady=2,
            ),
            "btn_violet",
        )
        self.img_ai_btn.pack(side="left", padx=(0, 4))
        self.img_clear_btn = reg(
            tk.Button(
                imgrow, text="✕", width=3, command=self.on_clear_image,
                relief="flat", bd=0, highlightthickness=1, font=("Segoe UI", 8, "bold"), cursor="hand2", pady=2,
            ),
            "btn_sec",
        )
        self.img_clear_btn.pack(side="left")

        imgprev = reg(tk.Frame(imgbox), "card_plain")
        imgprev.pack(fill="x", pady=(6, 0))
        thumb_holder = reg(tk.Frame(imgprev, width=92, height=50, highlightthickness=1, bd=0), "thumb_box")
        thumb_holder.pack_propagate(False)
        thumb_holder.pack(side="left")
        self.img_thumb = reg(tk.Label(thumb_holder, text="Görsel yok", font=("Segoe UI", 8)), "thumb")
        self.img_thumb.pack(fill="both", expand=True)
        self.img_thumb.bind("<Button-1>", self.on_preview_large_image)
        self.img_info = reg(
            tk.Label(
                imgprev, text="Görsel seçili değil (Dosya Seç veya YZ Resim Üret)",
                anchor="w", justify="left", font=("Segoe UI", 8), wraplength=310,
            ),
            "muted",
        )
        self.img_info.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # Kart 3: Hashtag İşaretleme (en az 30 mesaj)
        self.ht_frame = make_card(right_col, padx=10, pady=7)
        self.ht_frame.pack(fill="both", expand=True, pady=(6, 0))
        ht_hdr = reg(tk.Frame(self.ht_frame), "card_plain")
        ht_hdr.pack(fill="x", pady=(0, 4))
        reg(tk.Label(ht_hdr, text="Hashtag İşaretleme", font=("Segoe UI", 9, "bold")), "lbl").pack(side="left")
        reg(tk.Label(ht_hdr, text="'#' kelimeler • en az 30 mesaj", font=("Segoe UI", 8)), "muted").pack(side="right")

        self.ht_canvas = reg(tk.Canvas(self.ht_frame, height=96, highlightthickness=0, bd=0), "ht_canvas")
        ht_sb = tk.Scrollbar(self.ht_frame, orient="vertical", command=self.ht_canvas.yview)
        self.ht_rows_frame = reg(tk.Frame(self.ht_canvas), "card_plain")
        self.ht_rows_frame.grid_columnconfigure(0, weight=1)
        self._ht_win_id = self.ht_canvas.create_window((0, 0), window=self.ht_rows_frame, anchor="nw")
        self.ht_canvas.configure(yscrollcommand=ht_sb.set)
        ht_sb.pack(side="right", fill="y")
        self.ht_canvas.pack(side="left", fill="both", expand=True)
        self.ht_rows_frame.bind(
            "<Configure>",
            lambda e: self.ht_canvas.configure(scrollregion=self.ht_canvas.bbox("all")),
        )
        self.ht_canvas.bind(
            "<Configure>",
            lambda e: self.ht_canvas.itemconfigure(self._ht_win_id, width=e.width),
        )

        self.main_pane.add(self.editor_pane, minsize=340, stretch="always")
        self.main_pane.add(right_col, minsize=465, stretch="never")

        self.toggle_link()
        self.toggle_img()
        self._load_state()
        self._refresh_stt_devices(initial=True)
        self.apply_theme(self.theme)
        self._refresh_hashtag_rows()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.text.focus_set()

        self.update_count()
        self.root.after(150, self.poll_queue)
        threading.Thread(target=self.startup_connect, daemon=True).start()
        _stats_sync.reopen_and_flush()

    # --- arayüz yardımcıları

    def toggle_theme(self):
        new_theme = "dark" if self.theme == "light" else "light"
        self.apply_theme(new_theme)
        self._save_state()

    def _sync_conn_pill(self):
        t = _THEMES[self.theme]
        specs = {
            "ready": ("● Chrome Bağlı", t["ok_bg"], t["ok_fg"]),
            "login": ("● X Girişi Gerekli", t["danger_bg"], t["danger"]),
            "connecting": ("● Bağlanıyor...", t["warn_bg"], t["warn_fg"]),
        }
        txt, bg, fg = specs.get(self._conn_state, specs["connecting"])
        self.conn_pill.config(text=txt, bg=bg, fg=fg)

    def _update_char_ring(self, n):
        t = _THEMES[self.theme]
        over = n > LIMIT
        ratio = min(1.0, max(0.0, n / float(LIMIT)))
        extent = -max(1, round(359 * ratio)) if ratio > 0 else 0
        self._char_ring.config(bg=t["card"])
        self._char_ring.itemconfig(self._ring_bg_id, outline=t["ring_track"])
        self._char_ring.itemconfig(
            self._ring_arc_id,
            outline=(t["danger"] if over else t["primary"]),
            extent=extent,
        )

    def _on_chip_toggle(self):
        self._sync_action_chips()
        self.update_count()

    def _sync_action_chips(self):
        t = _THEMES[self.theme]
        enabled = bool(self.var_link.get())
        for ck, var in getattr(self, "_action_chips", ()):
            on = bool(var.get())
            if not enabled:
                ck.config(
                    bg=t["pill"], fg=t["muted"], selectcolor=t["pill"],
                    highlightbackground=t["card_border"], disabledforeground=t["muted"],
                    activebackground=t["pill"], activeforeground=t["muted"],
                )
            elif on:
                ck.config(
                    bg=t["primary"], fg="white", selectcolor=t["primary"],
                    highlightbackground=t["primary"],
                    activebackground=t["primary_hover"], activeforeground="white",
                )
            else:
                ck.config(
                    bg=t["sub"], fg=t["fg"], selectcolor=t["sub"],
                    highlightbackground=t["input_border"],
                    activebackground=t["pill"], activeforeground=t["fg"],
                )

    def _apply_hashtag_rows_theme(self):
        t = _THEMES[self.theme]
        for child in self.ht_rows_frame.winfo_children():
            cls = child.winfo_class()
            if cls == "Label":
                txt = str(child.cget("text") or "")
                child.config(bg=t["card"], fg=(t["link_x"] if txt.startswith("#") else t["muted"]))
            elif cls == "Checkbutton":
                child.config(
                    bg=t["card"], fg=t["fg"], activebackground=t["card"],
                    activeforeground=t["fg"], selectcolor=t["chk_select"],
                )
            elif cls == "Button":
                child.config(
                    bg=t["teal"], fg="white", activebackground=t["teal_hover"],
                    activeforeground="white",
                )

    def apply_theme(self, theme="light"):
        self.theme = "dark" if theme == "dark" else "light"
        t = _THEMES[self.theme]
        self.root.configure(bg=t["bg"])
        for w, role in self._t_items:
            try:
                if role == "bg":
                    w.config(bg=t["bg"])
                elif role == "sash":
                    w.config(bg=t["sash"])
                elif role == "card":
                    w.config(bg=t["card"], highlightbackground=t["card_border"])
                elif role == "card_plain":
                    w.config(bg=t["card"])
                elif role == "pill":
                    w.config(bg=t["pill"], highlightbackground=t["card_border"])
                elif role == "pill_lbl":
                    w.config(bg=t["pill"], fg=t["fg"])
                elif role == "pill_muted":
                    w.config(bg=t["pill"], fg=t["muted"])
                elif role == "badge_primary":
                    w.config(bg=t["primary"], fg="white")
                elif role == "lbl":
                    w.config(bg=t["card"], fg=t["fg"])
                elif role == "muted":
                    w.config(bg=t["card"], fg=t["muted"])
                elif role == "divider":
                    w.config(bg=t["card_border"])
                elif role == "ht_canvas":
                    w.config(bg=t["card"])
                elif role == "thumb_box":
                    w.config(bg=t["sub"], highlightbackground=t["input_border"])
                elif role == "thumb":
                    w.config(bg=t["sub"], fg=t["muted"])
                elif role == "entry":
                    w.config(
                        bg=t["sub"], fg=t["fg"], insertbackground=t["fg"],
                        disabledbackground=t["pill"], disabledforeground=t["muted"],
                        highlightbackground=t["input_border"], highlightcolor=t["primary"],
                    )
                elif role == "text":
                    w.config(
                        bg=t["sub"], fg=t["fg"], insertbackground=t["fg"],
                        highlightbackground=t["input_border"], highlightcolor=t["primary"],
                    )
                    if hasattr(w, "frame"):
                        w.frame.config(bg=t["card"])
                    w.tag_configure("over", background=t["over_bg"], foreground=t["over_fg"])
                elif role == "chk":
                    w.config(
                        bg=t["card"], fg=t["fg"], activebackground=t["card"],
                        activeforeground=t["fg"], selectcolor=t["chk_select"],
                    )
                elif role == "chk_pill":
                    w.config(
                        bg=t["pill"], fg=t["fg"], activebackground=t["pill"],
                        activeforeground=t["fg"], selectcolor=t["chk_select"],
                        highlightbackground=t["card_border"],
                    )
                elif role == "btn_sec":
                    w.config(
                        bg=t["btn_sec_bg"], fg=t["btn_sec_fg"],
                        activebackground=t["btn_sec_hover"], activeforeground=t["btn_sec_fg"],
                        highlightbackground=t["card_border"],
                    )
                elif role == "btn_primary":
                    w.config(
                        bg=t["primary"], fg="white",
                        activebackground=t["primary_hover"], activeforeground="white",
                    )
                elif role == "btn_emerald":
                    w.config(
                        bg=t["emerald"], fg="white",
                        activebackground=t["emerald_hover"], activeforeground="white",
                    )
                elif role == "btn_violet":
                    w.config(
                        bg=t["violet"], fg="white",
                        activebackground=t["violet_hover"], activeforeground="white",
                    )
                elif role == "scale":
                    w.config(
                        bg=t["card"], fg=t["fg"], troughcolor=t["pill"],
                        activebackground=t["primary"],
                    )
                elif role == "opt":
                    w.config(
                        bg=t["card"], fg=t["fg"],
                        activebackground=t["btn_sec_hover"], activeforeground=t["fg"],
                        highlightbackground=t["input_border"],
                    )
                    w["menu"].config(
                        bg=t["card"], fg=t["fg"],
                        activebackground=t["primary"], activeforeground="white",
                    )
                elif role == "link_x":
                    w.config(bg=t["card"], fg=t["link_x"])
                elif role == "link_yt":
                    w.config(bg=t["card"], fg=t["link_yt"])
            except Exception:
                pass
        self.theme_btn.config(text=("☀️ Açık" if self.theme == "dark" else "🌙 Koyu"))
        self.mic_meter.config(bg=t["meter_track"], highlightbackground=t["input_border"])
        self._sync_conn_pill()
        self._sync_action_chips()
        self._update_mic_ui()
        self._update_mic_meter(*self._last_meter)
        self._update_char_ring(self._char_count)
        self._apply_hashtag_rows_theme()
        over = self._char_count > LIMIT
        self.counter.config(
            fg=(t["danger"] if over else t["muted"]),
            bg=(t["danger_bg"] if over else t["pill"]),
        )
        self.set_status(self.status.cget("text"), error=self._status_err)

    def _on_clear_message(self):
        self.text.delete("1.0", "end")
        self.text.focus_set()
        self.update_count()
        self.set_status("Mesaj kutusu temizlendi.")

    def _on_tags_focus_out(self, event=None):
        self.save_tags()
        self.update_count()

    def build_final(self):
        """Gönderilecek metni oluştur: mesaj + (varsa) altına hashtag bloğu.
        Mesaj kutusu boşsa boş string döner (yalnızca kayıtlı hashtag gönderilmez)."""
        msg = self.text.get("1.0", "end-1c").strip()
        if not msg:
            return ""
        tags = self._yz_tags()
        return f"{msg}\n\n{tags}" if tags else msg

    def save_tags(self, event=None):
        try:
            with open(HASHTAGS_FILE, "w", encoding="utf-8") as f:
                f.write(self.tags.get("1.0", "end-1c"))
        except Exception:
            pass

    def update_count(self, event=None):
        raw = self.text.get("1.0", "end-1c")
        msg = raw.strip()
        tags = self._yz_tags()
        combined = msg + "\n\n" + tags if msg and tags else (msg or tags)
        n = len(combined)
        self._char_count = n
        t = _THEMES[self.theme]
        over = n > LIMIT
        self.counter.config(
            text=f"{n}/{LIMIT}",
            fg=(t["danger"] if over else t["muted"]),
            bg=(t["danger_bg"] if over else t["pill"]),
        )
        self._update_char_ring(n)
        self.save_tags()
        try:
            self._save_state()
        except Exception:
            pass
        # Limiti aşan kısım mesajın içindeyse o bölümü renklendir (yazmaya engel yok)
        self.text.tag_remove("over", "1.0", "end")
        overhead = (len(tags) + 2) if (msg and tags) else len(tags)
        msg_limit = max(0, LIMIT - overhead)
        if n > LIMIT and len(msg) > msg_limit:
            start = len(raw) - len(raw.lstrip())
            self.text.tag_add("over", f"1.0+{start + msg_limit}c", f"1.0+{start + len(msg)}c")
        sig_base = "".join(self.build_final().split())
        act_img = self._active_image_path()
        sig = (sig_base + ("|" + act_img if act_img else "")) if (sig_base or act_img) else ""
        if sig != self.last_send_sig:
            self._resend_armed = False
        # Uzunluk gönderi engellemez; yalnızca yapılacak iş kalmadığında kilitlenir
        if not self.busy:
            self.send_btn.config(state=("normal" if self._plan_ready() else "disabled"))
        self._refresh_hashtag_rows()

    def _set_mark_buttons_state(self):
        st = "disabled" if self.busy else "normal"
        for btn in self._ht_mark_btns:
            try:
                btn.config(state=st)
            except Exception:
                pass

    def _refresh_hashtag_rows(self):
        tags = _extract_hash_words(self.tags.get("1.0", "end-1c"))
        if tags == self._ht_rendered_tags:
            return
        self._ht_rendered_tags = list(tags)
        self._ht_mark_btns = []
        for child in self.ht_rows_frame.winfo_children():
            child.destroy()
        t = _THEMES[self.theme]
        if not tags:
            tk.Label(
                self.ht_rows_frame,
                text="Hashtag'ler kutusunda '#' ile başlayan kelime yok.",
                bg=t["card"], fg=t["muted"], font=("Segoe UI", 8), anchor="w",
            ).grid(row=0, column=0, columnspan=4, sticky="w", pady=4)
            return
        for r_idx, tag in enumerate(tags):
            k = tag.lower()
            if k not in self.ht_vars:
                pref = self._ht_pending_prefs.get(k, {})
                v_like = tk.BooleanVar(value=bool(pref.get("like", False)))
                v_repost = tk.BooleanVar(value=bool(pref.get("repost", False)))
                self.ht_vars[k] = (v_like, v_repost)
            else:
                v_like, v_repost = self.ht_vars[k]
            lbl_txt = tag if len(tag) <= 28 else (tag[:27] + "…")
            tk.Label(
                self.ht_rows_frame, text=lbl_txt, anchor="w",
                font=("Segoe UI", 8, "bold"), bg=t["card"], fg=t["link_x"],
            ).grid(row=r_idx, column=0, sticky="ew", padx=(0, 6), pady=2)
            tk.Checkbutton(
                self.ht_rows_frame, text="Like", variable=v_like, font=("Segoe UI", 8),
                bg=t["card"], fg=t["fg"], activebackground=t["card"],
                activeforeground=t["fg"], selectcolor=t["chk_select"],
                command=self._save_state,
            ).grid(row=r_idx, column=1, sticky="w", padx=(0, 4))
            tk.Checkbutton(
                self.ht_rows_frame, text="Repost", variable=v_repost, font=("Segoe UI", 8),
                bg=t["card"], fg=t["fg"], activebackground=t["card"],
                activeforeground=t["fg"], selectcolor=t["chk_select"],
                command=self._save_state,
            ).grid(row=r_idx, column=2, sticky="w", padx=(0, 6))
            btn = tk.Button(
                self.ht_rows_frame, text="İşaretle",
                command=lambda t_tag=tag: self.on_mark_hashtag(t_tag),
                bg=t["teal"], fg="white", relief="flat", bd=0,
                activebackground=t["teal_hover"], activeforeground="white",
                font=("Segoe UI", 8, "bold"), cursor="hand2", padx=8, pady=1,
                state=("disabled" if self.busy else "normal"),
            )
            btn.grid(row=r_idx, column=3, sticky="e", pady=2)
            self._ht_mark_btns.append(btn)

    def on_mark_hashtag(self, tag):
        if self.busy:
            return
        v_like, v_repost = self.ht_vars.get(tag.lower(), (None, None))
        do_like = bool(v_like and v_like.get())
        do_repost = bool(v_repost and v_repost.get())
        if not do_like and not do_repost:
            self.set_status(f"{tag} için önce Like ve/veya Repost seç.", error=True)
            return
        self.busy = True
        self.send_btn.config(state="disabled")
        self._set_mark_buttons_state()
        self._save_state()
        self.set_status(f"{tag} sayfasında en az {HASHTAG_MARK_TARGET} mesaj için işaretleme başlıyor...")
        threading.Thread(target=self.mark_hashtag_bg, args=(tag, do_like, do_repost), daemon=True).start()

    def mark_hashtag_bg(self, tag, do_like, do_repost):
        def done(ok):
            self.q.put(("__mark_done__", ok))

        mark_hashtag_plan(tag, do_like, do_repost, self._ui_log, done)

    def _active_image_path(self):
        p = (self.image_path or "").strip()
        if self.var_img.get() and p and os.path.isfile(p):
            return p
        return None

    def _plan_ready(self):
        """Gönderilecek en az bir iş var mı? (yeni mesaj/görsel VEYA link işlemleri)"""
        if self.var_post.get() and (self.build_final() or self._active_image_path()):
            return True
        if (self.var_link.get() and self.link_entry.get().strip()
                and (self.var_reply.get() or self.var_quote.get()
                     or self.var_like.get() or self.var_repost.get()
                     or self.var_bookmark.get())):
            return True
        return False

    def toggle_link(self):
        state = ("normal" if self.var_link.get() else "disabled")
        for ck in (self.ck_reply, self.ck_quote, self.ck_like, self.ck_repost, self.ck_bookmark):
            ck.config(state=state)
        self.link_entry.config(state=state)
        self._sync_action_chips()
        self._save_state()
        if hasattr(self, "send_btn"):
            self.update_count()

    def _set_img_buttons(self):
        enabled = bool(self.var_img.get()) and not bool(self.img_busy)
        st = "normal" if enabled else "disabled"
        for b in (self.img_pick_btn, self.img_ai_btn):
            b.config(state=st)
        self.img_clear_btn.config(state=("normal" if (enabled and bool(self.image_path)) else "disabled"))

    def _update_img_preview(self):
        p = (self.image_path or "").strip()
        valid = bool(p and os.path.isfile(p))
        self._thumb_photo = None
        if not valid:
            self.img_thumb.config(image="", text=("Görsel\nyok" if self.var_img.get() else "Pasif"), cursor="")
            if p and not os.path.exists(p):
                self.img_info.config(text="Önceki görsel dosyası bulunamadı — yeniden seç veya YZ ile üret.")
            elif self.var_img.get():
                self.img_info.config(text="Görsel seçili değil — Dosya Seç veya YZ Resim Üret kullan.")
            else:
                self.img_info.config(text="Resim Ekle kapalı — yalnızca metin gönderilir.")
            return

        thumb_ok = False
        if _PIL_OK:
            try:
                with _PilImage.open(p) as im:
                    im_copy = im.copy()
                im_copy.thumbnail((92, 50))
                self._thumb_photo = _PilImageTk.PhotoImage(im_copy)
                self.img_thumb.config(image=self._thumb_photo, text="", cursor="hand2")
                thumb_ok = True
            except Exception:
                pass
        if not thumb_ok:
            self.img_thumb.config(image="", text="Görsel\nhazır", cursor="hand2")

        prefix = "" if self.var_img.get() else "(Pasif — Resim Ekle kapalı) "
        name = os.path.basename(p)
        meta = (self.image_meta or name) + "\n(Büyütmek için küçük resme tıkla)"
        try:
            fsize = os.path.getsize(p)
            if fsize > MAX_MEDIA_BYTES:
                meta += f" • ⚠ {fsize / (1024 * 1024):.1f} MB (X sınırı ~5 MB)"
        except Exception:
            pass
        self.img_info.config(text=prefix + meta)

    def on_preview_large_image(self, event=None):
        """Küçük görsele tıklandığında tam boy önizleme penceresi açar (Esc veya tıkla ile kapanır)."""
        p = (self.image_path or "").strip()
        if not p or not os.path.isfile(p):
            return None
        try:
            if self._preview_win is not None and self._preview_win.winfo_exists():
                self._preview_win.destroy()
        except Exception:
            pass
        self._preview_win = None

        photo = None
        dims = ""
        if _PIL_OK:
            try:
                max_w = max(480, min(1150, int(self.root.winfo_screenwidth() * 0.85)))
                max_h = max(360, min(850, int(self.root.winfo_screenheight() * 0.82)))
                with _PilImage.open(p) as im:
                    orig_w, orig_h = im.size
                    dims = f" ({orig_w}×{orig_h})"
                    view_im = im.copy()
                resamp = getattr(getattr(_PilImage, "Resampling", _PilImage), "LANCZOS", _PilImage.BICUBIC)
                view_im.thumbnail((max_w, max_h), resamp)
                photo = _PilImageTk.PhotoImage(view_im)
            except Exception:
                photo = None
        if photo is None:
            try:
                photo = tk.PhotoImage(file=p)
            except Exception:
                try:
                    os.startfile(p)
                except Exception as e:
                    self.set_status(f"Görsel açılamadı: {e}", error=True)
                return None

        win = tk.Toplevel(self.root)
        win.title(f"Görsel Önizleme — {os.path.basename(p)}{dims}")
        win.configure(bg="#111827")
        win.transient(self.root)
        win._photo = photo
        lbl = tk.Label(win, image=photo, bg="#111827", cursor="hand2")
        lbl.pack(padx=10, pady=(10, 6))
        bar = tk.Frame(win, bg="#111827")
        bar.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(
            bar, text="Kapatmak için resme tıkla veya Esc'e bas",
            bg="#111827", fg="#9ca3af", font=("Segoe UI", 8),
        ).pack(side="left")
        tk.Button(
            bar, text="Kapat", command=win.destroy,
            bg="#374151", fg="white", relief="flat", font=("Segoe UI", 8, "bold"),
            padx=10, cursor="hand2",
        ).pack(side="right")
        lbl.bind("<Button-1>", lambda e: win.destroy())
        win.bind("<Escape>", lambda e: win.destroy())
        self._preview_win = win
        return win

    def toggle_img(self):
        self._set_img_buttons()
        self._update_img_preview()
        self._save_state()
        if hasattr(self, "send_btn"):
            self.update_count()

    def on_pick_image(self):
        if self.img_busy:
            return
        path = filedialog.askopenfilename(
            title="Mesaj için görsel seç",
            filetypes=[
                ("Görseller", "*.png *.jpg *.jpeg *.webp *.gif"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if not path:
            return
        self.var_img.set(True)
        self.image_path = path
        dims = ""
        if _PIL_OK:
            try:
                with _PilImage.open(path) as im:
                    dims = f" ({im.size[0]}×{im.size[1]})"
            except Exception:
                pass
        self.image_meta = f"Dosya: {os.path.basename(path)}{dims}"
        self._set_img_buttons()
        self._update_img_preview()
        self._save_state()
        self.update_count()
        try:
            if os.path.getsize(path) > MAX_MEDIA_BYTES:
                self.set_status("Uyarı: Seçilen görsel ~5 MB sınırının üstünde; X kabul etmeyebilir.", error=True)
                return
        except Exception:
            pass
        self.set_status(f"Görsel seçildi ✓ ({os.path.basename(path)})")

    def on_clear_image(self):
        if self.img_busy:
            return
        self.image_path = ""
        self.image_meta = ""
        try:
            if self._preview_win is not None and self._preview_win.winfo_exists():
                self._preview_win.destroy()
        except Exception:
            pass
        self._preview_win = None
        self._set_img_buttons()
        self._update_img_preview()
        self._save_state()
        self.update_count()
        self.set_status("Seçili görsel temizlendi.")

    def on_gen_image(self):
        if self.img_busy:
            return
        key = self.cloud_key.get().strip()
        if not key:
            self.set_status("YZ resim üretimi için Bulut Model bölümüne OpenRouter API Key gir.", error=True)
            return
        msg = self.text.get("1.0", "end-1c").strip()
        if not msg:
            self.set_status("Görsel üretmek için önce mesaj kutusuna (Ne paylaşmak istersin?) bir mesaj yaz veya üret.", error=True)
            return
        base = self.cloud_url.get().strip()
        model = self.cloud_model.get().strip()
        ratio = random.choice(IMAGE_RATIOS)
        style = _next_image_style(self.used_img_styles)
        msg_clean = _clean_msg_for_image(msg)
        focus_pts = _pick_focus_points(msg_clean, self.used_img_focuses, k=1) if msg_clean else []
        focus = focus_pts[0] if focus_pts else ""
        self.var_img.set(True)
        self.img_busy = True
        self._set_img_buttons()
        self.set_status(f"Mesaj İngilizce sahneye çevriliyor ({ratio})...")
        threading.Thread(
            target=self.img_generate,
            args=(key, base, model, msg, ratio, style, focus),
            daemon=True,
        ).start()

    def set_status(self, msg, error=False):
        self._status_err = bool(error)
        t = _THEMES[self.theme]
        self.status.config(text=msg, fg=(t["danger"] if error else t["muted"]))

    def _ui_log(self, msg, error=False):
        """Durumu arayüze yaz; ayrıca tanı için konsola/zygüğe de bırak."""
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {'HATA ' if error else ''}{msg}", flush=True)
        except Exception:
            pass
        self.q.put((msg, error))

    def poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "__done__":
                    self.busy = False
                    self.send_btn.config(text="Gönder ↗")
                    if item[1]:
                        self.text.delete("1.0", "end")
                        self._login_done.set()
                        self._conn_state = "ready"
                        self._sync_conn_pill()
                    self._set_mark_buttons_state()
                    self.update_count()
                elif kind == "__mark_done__":
                    self.busy = False
                    self.send_btn.config(text="Gönder ↗")
                    if item[1]:
                        self._login_done.set()
                        self._conn_state = "ready"
                        self._sync_conn_pill()
                    self._set_mark_buttons_state()
                    self.update_count()
                elif kind == "__ready__":
                    if item[1]:
                        self._login_done.set()
                        self._conn_state = "ready"
                    else:
                        self._conn_state = "login"
                    self._sync_conn_pill()
                    self.update_count()
                elif kind == "__yz_text__":
                    self.text.delete("1.0", "end")
                    self.text.insert("1.0", item[1])
                    self.update_count()
                    txt = (item[1] or "").strip()
                    if txt:
                        self.recent_outputs.append(txt)
                        if len(self.recent_outputs) > 5:
                            self.recent_outputs.pop(0)
                elif kind == "__yz_done__":
                    self.gen_busy = False
                    self.yz_btn.config(state="normal")
                    self.cloud_btn.config(state="normal")
                elif kind == "__img_ready__":
                    res = item[1]
                    self.var_img.set(True)
                    self.image_path = res["path"]
                    size = res.get("size")
                    sz = f" • {size[0]}×{size[1]}" if size else ""
                    self.image_meta = f"YZ ({res['aspect_ratio']}{sz}) • {res['model']}"
                    self._update_img_preview()
                    self._save_state()
                    self.update_count()
                elif kind == "__img_done__":
                    self.img_busy = False
                    self._set_img_buttons()
                elif kind == "__stt_event__":
                    self._handle_stt_event(item[1])
                else:
                    msg, err = item
                    self.set_status(msg, err)
        except queue.Empty:
            pass
        self.root.after(150, self.poll_queue)

    # --- olaylar

    def on_send(self):
        if self.busy:
            return
        post_new = self.var_post.get()
        do_link = self.var_link.get()
        link = self.link_entry.get().strip()
        reply = do_link and self.var_reply.get()
        quote = do_link and self.var_quote.get()
        like = do_link and self.var_like.get()
        repost = do_link and self.var_repost.get()
        bookmark = do_link and self.var_bookmark.get()
        if not post_new and not do_link:
            return
        if do_link and not link:
            self.set_status("Lütfen işlem yapılacak gönderinin linkini gir.", error=True)
            return
        if do_link and not (reply or quote or like or repost or bookmark):
            self.set_status("Link işlemi için en az birini seç: Reply / Quote / Like / Repost / Bookmark.", error=True)
            return
        img = None
        if self.var_img.get():
            raw_img = (self.image_path or "").strip()
            if raw_img:
                if not os.path.isfile(raw_img):
                    self.set_status("Seçili görsel dosyası bulunamadı; yeni görsel seç veya ✕ ile temizle.", error=True)
                    return
                img = raw_img
        text = self.build_final() if (post_new or reply or quote) else ""
        if (reply or quote) and not text and not img:
            self.set_status("Reply / Quote için mesaj kutusuna bir şeyler yaz veya görsel ekle.", error=True)
            return
        if post_new and not text and not img:
            if not do_link:
                return
            # Mesaj ve görsel boş ama link işlemleri isteniyor: yalnız onları yap
            post_new = False
            self.set_status("Mesaj kutusu boş — yalnızca link işlemleri yapılacak.")
        # Çift gönderim koruması: aynı metin+görsel 90 sn içinde tekrar gönderilmek
        # istenirse önce uyar, ikinci basışta onaylanmış sayar.
        sig_base = "".join(text.split())
        sig = (sig_base + ("|" + img if img else "")) if (sig_base or img) else ""
        now = time.time()
        if (sig and sig == self.last_send_sig
                and (now - self.last_send_time) < 90 and not self._resend_armed):
            self.set_status("⚠ Bu mesaj az önce gönderildi/gönderilmeye çalışıldı! "
                            "Yine de göndermek için GÖNDER'e tekrar bas.", error=True)
            self._resend_armed = True
            return
        self._resend_armed = False
        self.last_send_sig = sig
        self.last_send_time = now
        self.busy = True
        self.send_btn.config(state="disabled", text="Gönderiliyor...")
        self._set_mark_buttons_state()
        self.set_status("Gönderiliyor...")
        plan = {"post_new": post_new, "text": text, "image": img, "do_link": do_link, "link": link,
                "reply": reply, "quote": quote, "like": like, "repost": repost, "bookmark": bookmark}
        threading.Thread(target=self.send_plan, args=(plan,), daemon=True).start()

    # --- arka plan

    def send_plan(self, plan):
        def done(ok):
            self.q.put(("__done__", ok))

        send_plan(plan, self._ui_log, done)

    def _yz_tags(self):
        return self.tags.get("1.0", "end-1c").strip()

    def _gen_budget(self, tags):
        """X-UY işaretliyse: mesaj+hashtag toplamı 280'i aşmasın -> mesaj bütçesi.
        İşaretsizse uzun mod (800 karaktere kadar)."""
        if self.var_xuy.get():
            overhead = (len(tags) + 2) if tags else 0
            return max(60, LIMIT - overhead)
        return 800

    def _length_note(self):
        """Üretime verilen uzunluk yönergesi. X-UY kapalıyken somut bir uzunluk
        örneği de verilir — küçük modeller örnek uzunluğu taklit etme eğilimindedir."""
        if self.var_xuy.get():
            return "2-4 kısa cümle"
        return ("5-7 cümle, ayrıntılı olsun (mağduriyet, talep ve çağrı unsurları olsun). "
                "Hedef uzunluk örneği: 'Bu tablo artık kabul edilemez. Aylardır ödenmeyen "
                "paralar için hiçbir açıklama yok. Mağdurlar her kanaldan sesleniyor ama "
                "yetkililer kayıtsız. Kimse bu sessizliği tek başına kıramaz; birlikte "
                "talep etmeliyiz. Ödemeler yapılana kadar bu ses her yerden yankılanacak.'")

    def _on_temp_change(self, _val=None):
        if hasattr(self, "temp_val_lbl"):
            self.temp_val_lbl.config(text=f"{self._current_temp():.1f}")
        if getattr(self, "_loaded", False):
            self._save_state()

    def _current_temp(self):
        try:
            return max(0.3, min(1.3, round(float(self.var_temp.get()), 2)))
        except Exception:
            return 1.0

    def _focus_and_avoid(self, topic):
        focus_pts = _pick_focus_points(topic, self.used_focuses, k=3)
        focus = " | ".join(focus_pts)
        snippets = []
        for prev in self.recent_outputs[-4:]:
            first_line = prev.splitlines()[0].strip() if prev else ""
            if first_line:
                snippets.append('"' + first_line[:65] + '"')
        return focus, " ; ".join(snippets)

    def on_yz(self):
        if self.gen_busy:
            return
        topic = self.topic.get("1.0", "end-1c").strip()
        if not topic:
            self.set_status("Önce Konu alanına kısa bir konu yaz (örn: fon paralarının ödenmemesi).", error=True)
            return
        tags = self._yz_tags()
        cap = self._gen_budget(tags)
        note = self._length_note()
        angle = self._next_angle()
        temp = self._current_temp()
        focus, avoid = self._focus_and_avoid(topic)
        self.gen_busy = True
        self.yz_btn.config(state="disabled")
        self.cloud_btn.config(state="disabled")
        self.set_status("WebGPU modeli çalışıyor...")
        threading.Thread(
            target=self.yz_generate,
            args=(topic, tags, angle, cap, note, temp, focus, avoid),
            daemon=True,
        ).start()

    def on_cloud(self):
        if self.gen_busy:
            return
        topic = self.topic.get("1.0", "end-1c").strip()
        if not topic:
            self.set_status("Önce Konu alanına kısa bir konu yaz.", error=True)
            return
        base = self.cloud_url.get().strip()
        key = self.cloud_key.get().strip()
        model = self.cloud_model.get().strip()
        if not (base and key and model):
            self.set_status("Bulut için Base URL, API Key ve Model alanlarını doldur.", error=True)
            return
        tags = self._yz_tags()
        cap = self._gen_budget(tags)
        note = self._length_note()
        angle = self._next_angle()
        temp = self._current_temp()
        focus, avoid = self._focus_and_avoid(topic)
        self.gen_busy = True
        self.yz_btn.config(state="disabled")
        self.cloud_btn.config(state="disabled")
        self.set_status("Bulut modeli çalışıyor...")
        self._save_state()
        threading.Thread(
            target=self.cloud_generate,
            args=(topic, tags, angle, cap, note, base, key, model, temp, focus, avoid),
            daemon=True,
        ).start()

    def _next_angle(self):
        """Üslup açılarını sırayla değiştir: son 6 açı tekrar seçilmez."""
        _, angles = _yz_prompts()
        pool = [a for a in angles if a not in self.used_angles]
        src = pool or angles or ["net bir tespitle başla ve çağrıyla bitir"]
        a = random.choice(src)
        self.used_angles.append(a)
        if len(self.used_angles) > 6:
            self.used_angles.pop(0)
        return a

    def _get_sashes(self):
        try:
            if hasattr(self, "editor_pane") and self.editor_pane.winfo_height() > 160:
                y0 = self.editor_pane.sash_coord(0)[1]
                y1 = self.editor_pane.sash_coord(1)[1]
                if 0 < y0 < y1:
                    self._saved_sashes = [y0, y1]
                    return [y0, y1]
        except Exception:
            pass
        return self._saved_sashes

    def _apply_sashes(self, sashes):
        try:
            if not sashes or len(sashes) != 2:
                return
            self.editor_pane.update_idletasks()
            h = self.editor_pane.winfo_height()
            if h <= 160:
                return
            y0 = max(78, min(int(sashes[0]), h - 144))
            y1 = max(y0 + 68, min(int(sashes[1]), h - 76))
            self.editor_pane.sash_place(0, 0, y0)
            self.editor_pane.sash_place(1, 0, y1)
            self._saved_sashes = [y0, y1]
        except Exception:
            pass

    def _save_state(self, event=None):
        """Tüm girilen bilgileri state.json'a atomik yaz (uygulama her açılışta geri yükler).
        Önceki dosya her zaman .bak olarak korunur; state yüklenmeden yazılmaz."""
        if not getattr(self, "_loaded", False):
            return   # init sırasında boş form üzerine yazılmasın!
        tmp_path = None
        try:
            if os.path.exists(STATE_FILE):
                try:
                    shutil.copyfile(STATE_FILE, STATE_FILE + ".bak")
                except Exception:
                    pass
            payload = {
                "topic": self.topic.get("1.0", "end-1c"),
                "temperature": self._current_temp(),
                "cloud": {
                    "base_url": self.cloud_url.get(),
                    "api_key": self.cloud_key.get(),
                    "model": self.cloud_model.get(),
                },
                "ops": {
                    "post_new": self.var_post.get(),
                    "do_link": self.var_link.get(),
                    "reply": self.var_reply.get(),
                    "quote": self.var_quote.get(),
                    "like": self.var_like.get(),
                    "repost": self.var_repost.get(),
                    "bookmark": self.var_bookmark.get(),
                    "xuy": self.var_xuy.get(),
                },
                "image": {
                    "enabled": bool(self.var_img.get()),
                    "path": self.image_path,
                    "meta": self.image_meta,
                },
                "stt_sens": self.var_stt_sens.get(),
                "theme": self.theme,
            }
            ht_marks = dict(self._ht_pending_prefs)
            for k, (vl, vr) in self.ht_vars.items():
                ht_marks[k] = {"like": bool(vl.get()), "repost": bool(vr.get())}
            if ht_marks:
                payload["hashtag_marks"] = ht_marks
            sashes = self._get_sashes()
            if sashes:
                payload["sashes"] = sashes
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=APP_DIR, prefix=".state_", suffix=".tmp", delete=False
            ) as tf:
                tmp_path = tf.name
                json.dump(payload, tf, ensure_ascii=False)
            os.replace(tmp_path, STATE_FILE)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            self._loaded = True
            return
        try:
            if st.get("topic"):
                self.topic.insert("1.0", st["topic"])
            c = st.get("cloud", {})
            t_val = st.get("temperature")
            if t_val is None:
                t_val = c.get("temperature")
            if t_val is not None:
                try:
                    self.var_temp.set(max(0.3, min(1.3, round(float(t_val), 1))))
                except Exception:
                    pass
            if hasattr(self, "temp_val_lbl"):
                self.temp_val_lbl.config(text=f"{self._current_temp():.1f}")
            if c.get("base_url"):
                self.cloud_url.insert(0, c["base_url"])
            if c.get("api_key"):
                self.cloud_key.insert(0, c["api_key"])
            if c.get("model"):
                self.cloud_model.insert(0, c["model"])
            ops = st.get("ops", {})
            if "post_new" in ops:
                self.var_post.set(bool(ops["post_new"]))
            if "do_link" in ops:
                self.var_link.set(bool(ops["do_link"]))
            if "reply" in ops:
                self.var_reply.set(bool(ops["reply"]))
            if "quote" in ops:
                self.var_quote.set(bool(ops["quote"]))
            if "like" in ops:
                self.var_like.set(bool(ops["like"]))
            if "repost" in ops:
                self.var_repost.set(bool(ops["repost"]))
            if "bookmark" in ops:
                self.var_bookmark.set(bool(ops["bookmark"]))
            if "xuy" in ops:
                self.var_xuy.set(bool(ops["xuy"]))
            ht_marks = st.get("hashtag_marks")
            if isinstance(ht_marks, dict):
                self._ht_pending_prefs = {
                    str(k).lower(): v for k, v in ht_marks.items() if isinstance(v, dict)
                }
                for k, (vl, vr) in self.ht_vars.items():
                    pref = self._ht_pending_prefs.get(k)
                    if isinstance(pref, dict):
                        vl.set(bool(pref.get("like", False)))
                        vr.set(bool(pref.get("repost", False)))
            img_st = st.get("image") or {}
            if "enabled" in img_st:
                self.var_img.set(bool(img_st["enabled"]))
            raw_img = (img_st.get("path") or "").strip()
            if raw_img and os.path.isfile(raw_img):
                self.image_path = raw_img
                self.image_meta = img_st.get("meta") or f"Dosya: {os.path.basename(raw_img)}"
            self.toggle_link()
            self.toggle_img()
            sashes = st.get("sashes")
            if isinstance(sashes, list) and len(sashes) == 2:
                self._saved_sashes = [int(sashes[0]), int(sashes[1])]
                self.root.after(80, lambda s=self._saved_sashes: self._apply_sashes(s))
            stt_sens = st.get("stt_sens")
            if stt_sens in _STT_SENS_LABELS:
                self.var_stt_sens.set(stt_sens)
            if st.get("theme") in _THEMES:
                self.theme = st["theme"]
        except Exception:
            pass
        finally:
            self._loaded = True   # yükleme bitti; artık kayıt açılabilir

    def _on_close(self):
        self._stt_cancel = True
        self._stt_accept_text = False
        self._stt_run_id += 1
        try:
            self.stt_controller.abort()
        except Exception:
            pass
        try:
            if self._stt_perm_win is not None and self._stt_perm_win.winfo_exists():
                self._stt_perm_win.destroy()
        except Exception:
            pass
        self._save_state()
        try:
            _stats_sync.close(wait_timeout=0.35)
        except Exception:
            pass
        self.root.destroy()

    # --- Türkçe STT (tam bağımsız yerel sesle yazım)

    def _is_stale_stt(self, run_id):
        return self._stt_cancel or (run_id is not None and run_id != self._stt_run_id)

    def _refresh_stt_devices(self, initial=False):
        devs = list_input_devices()
        self._stt_devices = devs
        menu = self.mic_dev_menu["menu"]
        menu.delete(0, "end")
        t = _THEMES[self.theme]
        menu.config(
            bg=t["card"], fg=t["fg"],
            activebackground=t["primary"], activeforeground="white",
        )
        if not devs:
            self.var_stt_dev.set("Mikrofon bulunamadı")
            self._stt_device_index = None
            menu.add_command(label="Mikrofon bulunamadı", state="disabled")
            if not initial:
                self.mic_status.config(text="Mikrofon bulunamadı", fg=t["danger"])
                self.set_status("Bilgisayarda kullanılabilir bir mikrofon cihazı bulunamadı.", error=True)
            return

        chosen = devs[0]
        if self._stt_device_index is not None:
            for d in devs:
                if d["index"] == self._stt_device_index:
                    chosen = d
                    break
        self._stt_device_index = chosen["index"]
        self.var_stt_dev.set(chosen["label"])
        for d in devs:
            lbl = d["label"]
            menu.add_command(label=lbl, command=lambda v=lbl: self._select_stt_device(v))
        if not initial:
            self.set_status(f"Mikrofon listesi güncellendi ({len(devs)} cihaz) — aktif: {chosen['name']}.")

    def _select_stt_device(self, label):
        t = _THEMES[self.theme]
        self.var_stt_dev.set(label)
        chosen = None
        for d in self._stt_devices:
            if d["label"] == label:
                chosen = d
                break
        if chosen is None:
            return
        self._stt_device_index = chosen["index"]
        if self.stt_state in ("loading", "listening"):
            sens = _STT_SENS_LABELS.get(self.var_stt_sens.get(), "normal")
            self._stt_cancel = True
            self.stt_controller.abort()
            self._stt_run_id += 1
            rid = self._stt_run_id
            self.stt_state = "loading"
            self._stt_cancel = False
            self._stt_accept_text = True
            self._update_mic_ui()
            self._update_mic_meter(0.0, active=True)
            self.mic_status.config(text="Mikrofon değiştiriliyor...", fg=t["warn_fg"])
            self.set_status(f"Mikrofon değiştirildi: {chosen['name']} — dinleme yeniden başlatılıyor...")
            threading.Thread(target=self._stt_start_bg, args=(sens, rid), daemon=True).start()
        else:
            self.mic_status.config(text=f"Seçili: {chosen['name'][:30]}", fg=t["muted"])
            self.set_status(f"Mikrofon seçildi: {chosen['name']}")

    def _ask_stt_permission(self):
        """Sesle yazım öncesi uygulamanın kendi arayüzünde mikrofon izni ve cihaz seçimi sor."""
        self._refresh_stt_devices(initial=True)
        devs = self._stt_devices
        if not devs:
            self.set_status("Bilgisayarda kullanılabilir bir mikrofon cihazı bulunamadı.", error=True)
            self.mic_status.config(text="Mikrofon bulunamadı", fg=_THEMES[self.theme]["danger"])
            return False

        t = _THEMES[self.theme]
        win = tk.Toplevel(self.root)
        win.title("Mikrofon İzni")
        win.configure(bg=t["bg"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._stt_perm_win = win

        card = tk.Frame(
            win, bg=t["card"], highlightbackground=t["card_border"],
            highlightthickness=1, bd=0, padx=16, pady=14,
        )
        card.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(
            card, text="🎙 Mikrofon Erişim İzni", bg=t["card"], fg=t["fg"],
            font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            text=(
                "X Poster sesle yazım için mikrofonunuzu kullanmak istiyor.\n"
                "Ses tanıma tamamen yerel olarak bu uygulamada çalışır; mikrofonu istediğiniz zaman ana ekrandan değiştirebilirsiniz."
            ),
            bg=t["card"], fg=t["muted"], font=("Segoe UI", 9),
            justify="left", anchor="w", wraplength=380,
        ).pack(fill="x", pady=(6, 10))

        labels = [d["label"] for d in devs]
        cur_lbl = self.var_stt_dev.get()
        sel_var = tk.StringVar(value=(cur_lbl if cur_lbl in labels else labels[0]))
        tk.Label(card, text="Mikrofon Cihazı:", bg=t["card"], fg=t["fg"], font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
        opt = tk.OptionMenu(card, sel_var, *labels)
        opt.config(
            bg=t["sub"], fg=t["fg"], activebackground=t["pill"], activeforeground=t["fg"],
            highlightbackground=t["input_border"], highlightthickness=1, relief="flat", bd=0,
            font=("Segoe UI", 9), anchor="w",
        )
        opt["menu"].config(
            bg=t["card"], fg=t["fg"], activebackground=t["primary"], activeforeground="white",
        )
        opt.pack(fill="x", pady=(3, 12))

        res = {"ok": False}

        def on_allow():
            chosen = sel_var.get()
            idx = devs[0]["index"]
            for d in devs:
                if d["label"] == chosen:
                    idx = d["index"]
                    break
            self._stt_device_index = idx
            self.var_stt_dev.set(chosen)
            res["ok"] = True
            win.destroy()

        def on_deny():
            res["ok"] = False
            win.destroy()

        btns = tk.Frame(card, bg=t["card"])
        btns.pack(fill="x")
        deny_btn = tk.Button(
            btns, text="İptal", command=on_deny,
            bg=t["btn_sec_bg"], fg=t["btn_sec_fg"], relief="flat", bd=0,
            activebackground=t["btn_sec_hover"], activeforeground=t["btn_sec_fg"],
            highlightthickness=1, highlightbackground=t["card_border"],
            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=12, pady=4,
        )
        deny_btn.pack(side="right", padx=(8, 0))
        allow_btn = tk.Button(
            btns, text="İzin Ver ve Başlat", command=on_allow,
            bg=t["primary"], fg="white", relief="flat", bd=0,
            activebackground=t["primary_hover"], activeforeground="white",
            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=14, pady=4,
        )
        allow_btn.pack(side="right")

        win.protocol("WM_DELETE_WINDOW", on_deny)
        win.bind("<Escape>", lambda _e: on_deny())
        win.bind("<Return>", lambda _e: on_allow())
        win.update_idletasks()
        try:
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_reqwidth()) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_reqheight()) // 2)
            win.geometry(f"+{px}+{py}")
        except Exception:
            pass
        allow_btn.focus_set()
        try:
            self.root.wait_window(win)
        finally:
            self._stt_perm_win = None
        return res["ok"]

    def _update_mic_ui(self):
        t = _THEMES[self.theme]
        st = self.stt_state
        styles = {
            "idle": ("🎤 Sesle Yaz", t["primary"], "white", t["primary_hover"], "white", "normal"),
            "loading": ("⏳ Hazırlanıyor (İptal)", t["warn_bg"], t["warn_fg"], t["warn_bg"], t["warn_fg"], "normal"),
            "listening": ("⏹ Dinliyor (Durdur)", t["danger"], "white", t["danger"], "white", "normal"),
            "stopping": ("⏳ Yazılıyor...", t["pill"], t["muted"], t["pill"], t["muted"], "normal"),
        }
        txt, bg, fg, abg, afg, btn_state = styles.get(st, styles["idle"])
        self.mic_btn.config(text=txt, bg=bg, fg=fg, activebackground=abg, activeforeground=afg, state=btn_state)

    def _append_dictated_text(self, piece):
        t = (piece or "").strip()
        if not t:
            return
        cur = self.text.get("1.0", "end-1c")
        sep = " " if (cur and not cur[-1].isspace()) else ""
        self.text.insert("end-1c", sep + t)
        self.text.see("end")
        self.update_count()

    def _on_stt_event(self, data):
        self.q.put(("__stt_event__", data))

    def _update_mic_meter(self, level=0.0, threshold=0.0012, speaking=False, active=True):
        self._last_meter = (level, threshold, speaking, active)
        t = _THEMES[self.theme]
        try:
            w = max(40, self.mic_meter.winfo_width() or int(self.mic_meter["width"]))
            h = max(10, self.mic_meter.winfo_height() or int(self.mic_meter["height"]))
            if not active:
                self.mic_meter.coords(self._meter_fill, 0, 0, 0, h)
                self.mic_meter.itemconfig(self._meter_fill, fill=t["meter_idle"])
                self.mic_meter.coords(self._meter_thr, -10, 0, -10, h)
                return
            lvl = max(float(level or 0.0), 1e-4)
            pct = max(0.0, min(1.0, (math.log10(lvl) + 4.0) / 3.3)) if (level or 0.0) > 0 else 0.0
            thr = max(float(threshold or 0.0012), 1e-4)
            thr_pct = max(0.0, min(1.0, (math.log10(thr) + 4.0) / 3.3))
            fill = t["ok"] if speaking else (t["meter_low"] if (level or 0.0) > 0 else t["meter_idle"])
            self.mic_meter.coords(self._meter_fill, 0, 0, int(round(pct * w)), h)
            self.mic_meter.itemconfig(self._meter_fill, fill=fill)
            tx = int(round(thr_pct * w))
            self.mic_meter.coords(self._meter_thr, tx, 0, tx, h)
            self.mic_meter.itemconfig(self._meter_thr, fill=t["danger"])
        except Exception:
            pass

    def _handle_stt_event(self, ev):
        if not isinstance(ev, dict):
            return
        ev_sid = ev.get("sid")
        if ev_sid is not None and ev_sid != self._stt_run_id:
            return
        t = _THEMES[self.theme]
        kind = ev.get("type")
        if kind == "listening":
            if self._stt_cancel:
                return
            self.stt_state = "listening"
            self._stt_accept_text = True
            self._update_mic_ui()
            self._update_mic_meter(0.0, active=True)
            dev = ev.get("device") or ""
            badge = f" ({dev})" if dev else ""
            self.mic_status.config(text=f"● Dinliyorum{badge} — konuşun", fg=t["danger"])
            self.set_status(f"Mikrofon açık ✓{badge} Konuşun — cümleler mesaj kutusuna canlı yazılır.")
        elif kind == "done":
            self.stt_state = "idle"
            self._stt_cancel = False
            self._stt_accept_text = False
            self._update_mic_ui()
            self._update_mic_meter(0.0, active=False)
            err = ev.get("error")
            if ev.get("ok"):
                self.mic_status.config(text="Türkçe STT • hazır", fg=t["ok"])
                self.set_status("Sesli yazım tamamlandı ✓ Gönder'e basabilir veya düzenleyebilirsin.")
            elif err:
                self._stt_perm_granted = False
                self.mic_status.config(text=err[:42], fg=t["danger"])
                self.set_status(err, error=True)
            else:
                self.mic_status.config(text="Türkçe STT • iptal edildi", fg=t["muted"])
                self.set_status("Sesli yazım iptal edildi.")
        elif kind == "level":
            if self.stt_state in ("listening", "stopping"):
                self._update_mic_meter(
                    ev.get("level", 0.0),
                    ev.get("threshold", 0.0012),
                    bool(ev.get("speaking", False)),
                    active=True,
                )
        elif kind == "text":
            if self._stt_accept_text:
                self._append_dictated_text(ev.get("text"))
                if self.stt_state == "listening":
                    self.mic_status.config(text="● Dinliyorum — yazıldı ✓", fg=t["ok"])
        elif kind == "progress":
            msg = (ev.get("message") or "").strip()
            if msg:
                self.mic_status.config(text=msg[:42], fg=t["warn_fg"])
                self.set_status(f"STT: {msg}")
        elif kind == "state":
            st = ev.get("state")
            if st == "speech" and self.stt_state == "listening":
                self.mic_status.config(text="🎙 Konuşma algılandı...", fg=t["ok"])
            elif st == "transcribing" and self.stt_state in ("listening", "stopping"):
                self.mic_status.config(text="✍ Yazıya dökülüyor...", fg=t["primary"])
            elif st == "listening" and self.stt_state == "listening":
                self.mic_status.config(text="● Dinliyorum — konuşun", fg=t["danger"])
            elif st in ("no_signal", "muted") and self.stt_state == "listening":
                self.mic_status.config(text="⚠ Ses gelmiyor — mikrofonu kontrol et", fg=t["warn_fg"])
                self.set_status(ev.get("detail") or "Mikrofondan ses verisi gelmiyor.", error=True)
        elif kind == "error":
            msg = (ev.get("message") or "STT hatası").strip()
            self.mic_status.config(text=msg[:42], fg=t["danger"])
            self.set_status(f"STT hatası: {msg}", error=True)

    def _on_stt_sens_change(self, _val=None):
        self._save_state()
        sens = _STT_SENS_LABELS.get(self.var_stt_sens.get(), "normal")
        self.stt_controller.set_sensitivity(sens)

    def on_stt_toggle(self):
        t = _THEMES[self.theme]
        if self.stt_state == "idle":
            if not self._stt_perm_granted:
                if not self._ask_stt_permission():
                    self.mic_status.config(text="Mikrofon izni verilmedi", fg=t["muted"])
                    self.set_status("Mikrofon izni verilmedi.", error=True)
                    return
                self._stt_perm_granted = True
            sens = _STT_SENS_LABELS.get(self.var_stt_sens.get(), "normal")
            self._stt_run_id += 1
            rid = self._stt_run_id
            self.stt_state = "loading"
            self._stt_cancel = False
            self._stt_accept_text = True
            self._update_mic_ui()
            self.mic_status.config(text="STT hazırlanıyor...", fg=t["warn_fg"])
            self.set_status("Yerel Türkçe ses tanıma (STT) hazırlanıyor...")
            threading.Thread(target=self._stt_start_bg, args=(sens, rid), daemon=True).start()
        elif self.stt_state in ("loading", "stopping"):
            was_loading = (self.stt_state == "loading")
            self._stt_cancel = True
            self._stt_accept_text = False
            self._stt_run_id += 1
            try:
                self.stt_controller.abort()
            except Exception:
                pass
            self.stt_state = "idle"
            self._update_mic_ui()
            self._update_mic_meter(0.0, active=False)
            msg = "İptal edildi • tekrar basabilirsin" if was_loading else "Durduruldu • hazır"
            self.mic_status.config(text=msg, fg=t["muted"])
            self.set_status("STT iptal edildi — tekrar başlatabilirsin." if was_loading else "Sesli yazım durduruldu.")
        elif self.stt_state == "listening":
            rid = self._stt_run_id
            self.stt_state = "stopping"
            self._update_mic_ui()
            self.mic_status.config(text="Son cümle yazılıyor...", fg=t["primary"])
            self.set_status("Mikrofon kapatılıyor, kalan ses yazıya dökülüyor...")
            threading.Thread(target=self._stt_stop_bg, kwargs={"run_id": rid}, daemon=True).start()

    def _stt_start_bg(self, sens, run_id=None):
        if run_id is None:
            run_id = self._stt_run_id
        self.stt_controller.start(
            run_id=run_id,
            sens=sens,
            device_index=self._stt_device_index,
            is_stale=lambda: self._is_stale_stt(run_id),
        )

    def _stt_stop_bg(self, quiet=False, run_id=None):
        self.stt_controller.stop()

    def img_generate(self, key, base, model, message, ratio, style="", focus=""):
        log = self._ui_log
        ok = False
        try:
            prompt = _translate_message_to_image_prompt(
                message, key, base_url=base, model=model, style=style, focus=focus, log=log
            )
            log(f"YZ görsel üretiyor ({ratio}): {prompt[:90]}...")
            res = _generate_cloud_image(key, prompt, ratio, base_url=base, model=IMAGE_MODEL)
            self.q.put(("__img_ready__", res))
            track_counter(COUNTER_IMAGE)
            log(f"YZ görsel hazır ✓ ({res['aspect_ratio']})")
            ok = True
        except Exception as e:
            traceback.print_exc()
            log(f"YZ görsel hatası: {e}", error=True)
        finally:
            self.q.put(("__img_done__", ok))

    def yz_generate(self, topic, tags, angle, cap, note, temp=1.0, focus="", avoid=""):
        log = self._ui_log

        def done(ok):
            self.q.put(("__yz_done__", ok))

        try:
            if not ensure_chrome(log):
                done(False)
                return
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                tab = _ensure_model_tab(context, log)
                log(f"WebGPU cümle üretiyor (sıcaklık {temp:.1f})...")
                # 1. aşama: kısa taslak — uzun modda da KISA üretilir, sonra genişletilir
                first_cap = min(cap, 280)
                first_note = note if cap <= 280 else "2-4 kısa cümle"
                out = tab.evaluate(
                    "([t, g, a, c, n, temp, f, av]) => window.generate(t, g, a, c, n, temp, f, av)",
                    [topic, tags, angle, first_cap, first_note, temp, focus, avoid],
                )
                out = _clean_yz(out, first_cap)
                if cap > 280 and out:
                    # Uzun mod: küçük modeller uzunluğu baştan tutturamıyor;
                    # kısa taslağı 5-7 cümleye genişlet (iki aşama, güvenilir).
                    log("Uzun mod: metin 5-7 cümleye genişletiliyor...")
                    out2 = tab.evaluate("([t, temp, f]) => window.expand(t, temp, f)", [out, temp, focus])
                    expanded = _clean_yz(out2, cap)
                    if len(expanded) > len(out):   # genişletme başarısızsa kısa hali koru
                        out = expanded
                if not out or len(out) < 10:
                    raise RuntimeError("model kullanılabilir bir metin üretmedi")
                self.q.put(("__yz_text__", out))
                track_counter(COUNTER_AI_MSG)
                log("WebGPU üretimi tamam ✓")
                done(True)
        except Exception as e:
            traceback.print_exc()
            log(f"WebGPU hatası: {e}", error=True)
            done(False)

    def cloud_generate(self, topic, tags, angle, cap, note, base, key, model,
                       temp=1.0, focus="", avoid=""):
        log = self._ui_log

        def done(ok):
            self.q.put(("__yz_done__", ok))

        try:
            system, _ = _yz_prompts()
            if not system:
                raise RuntimeError("prompt.json okunamadı")
            user = _build_yz_user_prompt(topic, tags, angle, cap, note, focus, avoid)
            log(f"Bulut modeli çağrılıyor (sıcaklık {temp:.1f})...")
            raw = _cloud_chat(base, key, model, system, user, temperature=temp)
            out = _clean_yz(raw, cap)
            if cap > 280 and out and len(out) < 220:
                log("Metin kısa kaldı; konu odağıyla 5-7 cümleye genişletiliyor...")
                expand_sys = ("Sen Türkçe metin editörüsün. Verilen taslağı konusunu, odağını ve "
                              "üslubunu koruyarak 5-7 cümleye genişlet. Sadece genişletilmiş metni yaz; "
                              "hashtag, emoji, tırnak ve açıklama yok. Kusursuz Türkçe imla.")
                expand_usr = ("Taslak: " + out
                              + ("\nOdaklanılacak ayrıntılar: " + focus if focus else "")
                              + "\nEn fazla " + str(cap) + " karakter.")
                expanded = _clean_yz(_cloud_chat(base, key, model, expand_sys, expand_usr, temperature=temp), cap)
                if len(expanded) > len(out):
                    out = expanded
            if not out or len(out) < 10:
                raise RuntimeError("çıktı temizlendikten sonra boş kaldı; ham çıktı: " + repr(raw[:150]))
            self.q.put(("__yz_text__", out))
            track_counter(COUNTER_AI_MSG)
            log("Bulut üretimi tamam ✓")
            done(True)
        except Exception as e:
            traceback.print_exc()
            log(f"Bulut hatası: {e}", error=True)
            done(False)

    def _launch_author_link(self, key, status_msg, target_fn):
        now = time.time()
        if (now - self._last_link_clicks.get(key, 0.0)) < 1.5:
            return
        self._last_link_clicks[key] = now
        self.set_status(status_msg)
        threading.Thread(
            target=target_fn,
            kwargs={"log": self._ui_log},
            daemon=True,
        ).start()

    def on_open_author_x(self, _event=None):
        self._launch_author_link(
            "x",
            f"@{AUTHOR_X_HANDLE} için X mesaj ekranı açılıyor...",
            lambda log=None: _open_x_message_screen(handle=AUTHOR_X_HANDLE, log=log),
        )

    def on_open_youtube(self, _event=None):
        self._launch_author_link(
            "yt",
            f"YouTube: @{AUTHOR_YT_HANDLE} kanalı açılıyor...",
            lambda log=None: _open_youtube_channel(handle=AUTHOR_YT_HANDLE, log=log),
        )

    def startup_connect(self):
        log = self._ui_log

        if not ensure_chrome(log):
            self.q.put(("__ready__", False))
            return
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                # Uygulama her açılışta temiz başlasın: önceki oturumdan kalan /stt/ veya hatalı YZ sekmelerini kapat
                _close_local_tabs(context, "/stt/")
                yz_tab = _find_local_tab(context, "/model.html")
                if yz_tab is not None:
                    try:
                        if yz_tab.evaluate("window.lastError ? window.lastError() : null"):
                            yz_tab.close()
                    except Exception:
                        pass
                page = find_x_page(context)
                logged = is_logged_in(page, timeout=4000)
        except Exception as e:
            log(f"Hata: {e}", error=True)
            self.q.put(("__ready__", False))
            return

        if logged:
            log("Hazır ✓ Mesajını yaz, Gönder'e bas (Ctrl+Enter da çalışır).")
            self.q.put(("__ready__", True))
        else:
            log("Bu Chrome penceresinde X'e giriş yapılmamış. Lütfen pencerede giriş yap; "
                "ben otomatik kontrol edeceğim (bu pencereyi kapatma).", error=True)
            self.q.put(("__ready__", False))
            threading.Thread(target=self.poll_login, daemon=True).start()

    def poll_login(self):
        log = self._ui_log

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = find_x_page(context)
                for _ in range(200):  # ~10 dakika
                    if self._login_done.is_set():
                        return
                    if is_logged_in(page, timeout=1500):
                        if not self._login_done.is_set():
                            log("Giriş tamamlandı. Hazır ✓ Artık mesaj yazıp Gönder'e basabilirsin.")
                            self.q.put(("__ready__", True))
                        return
                    time.sleep(3)
        except Exception:
            pass
        if not self._login_done.is_set():
            log("Giriş hâlâ yapılmadı. Gönder'e bastığında tekrar deneyeceğim.", error=True)


if __name__ == "__main__":
    root = tk.Tk()
    XPoster(root)
    root.mainloop()
