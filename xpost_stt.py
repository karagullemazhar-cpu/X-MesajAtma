# -*- coding: utf-8 -*-
"""
X Poster için tam bağımsız yerli Türkçe STT (Konuşma -> Metin) modülü.

Herhangi bir harici tarayıcı sekmesine, CDN'e veya başka bir uygulamaya
bağlı kalmadan mikrofon sesini `sounddevice` ile doğrudan yakalar, enerji tabanlı
VAD ile cümlelere böler ve `faster-whisper` (CUDA GPU / CPU) ile yazıya döker.
"""

import glob
import os
import queue
import re
import sys
import threading
import time

import numpy as np

try:
    import sounddevice as sd
    _SD_OK = True
except Exception:
    sd = None
    _SD_OK = False

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STT_MODELS_DIR = os.path.join(APP_DIR, "stt_models")
DEFAULT_STT_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
TARGET_RATE = 16000

SENSITIVITIES = {
    "quiet":  {"abs_min": 0.0006, "noise_mult": 2.4, "label": "Sessiz"},
    "normal": {"abs_min": 0.0012, "noise_mult": 3.0, "label": "Normal"},
    "noisy":  {"abs_min": 0.0030, "noise_mult": 3.8, "label": "Gürültülü"},
}

# Whisper'ın sessizlik/parazit üzerinde ürettiği kalıplar
_SUSPECT_PATTERNS = (
    re.compile(r"^altyaz[ıi]\s*m\.?\s*k\.?$", re.I),
    re.compile(r"^altyaz[ıi]\b", re.I),
    re.compile(r"izlediğiniz için teşekkür", re.I),
    re.compile(r"abone olmay[ıi] unutmay", re.I),
    re.compile(r"^kanal[ıi]m[ıi]za\b", re.I),
    re.compile(r"^www\.", re.I),
    re.compile(r"^teşekkürler\.?$", re.I),
)

_cuda_lock = threading.Lock()
_cuda_ready = False


def ensure_cuda_dlls():
    """site-packages/nvidia/*/bin altındaki CUDA/cuDNN DLL yollarını sürece tanıt."""
    global _cuda_ready
    with _cuda_lock:
        if _cuda_ready:
            return
        added = []
        for sp in list(sys.path):
            if not sp or not os.path.isdir(sp):
                continue
            for p in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
                if os.path.isdir(p) and p not in added:
                    added.append(p)
                    try:
                        os.add_dll_directory(p)
                    except Exception:
                        pass
                    cur_path = os.environ.get("PATH", "")
                    if p not in cur_path:
                        os.environ["PATH"] = p + os.pathsep + cur_path
        _cuda_ready = True


def filter_transcript(text, last_text="", last_at=0.0, now=None):
    """Kısa halüsinasyonları ve 2 sn içindeki birebir whisper tekrarlarını ele."""
    t = (text or "").strip()
    if not t or not any(ch.isalnum() for ch in t):
        return None
    if len(t.split()) < 12 and any(p.search(t) for p in _SUSPECT_PATTERNS):
        return None
    ts = time.monotonic() if now is None else now
    if last_text and t == last_text and (ts - last_at) < 2.0:
        return None
    return t


class LinearResampler:
    """Doğrusal interpolasyonla akış yeniden örnekleyici (ör. 48 kHz -> 16 kHz)."""

    def __init__(self, from_rate, to_rate=TARGET_RATE):
        self.step = float(from_rate) / float(to_rate)
        self.pos = 0.0
        self.carry = np.zeros(0, dtype=np.float32)

    def process(self, chunk):
        arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return arr
        buf = np.concatenate((self.carry, arr)) if self.carry.size else arr
        usable = buf.size - 1.0 - self.pos
        out_len = int(usable // self.step) if usable > 0 else 0
        if out_len <= 0:
            consumed = int(self.pos)
            self.carry = buf[consumed:].copy()
            self.pos -= consumed
            return np.zeros(0, dtype=np.float32)
        positions = self.pos + np.arange(out_len, dtype=np.float64) * self.step
        idx0 = np.floor(positions).astype(np.int64)
        frac = (positions - idx0).astype(np.float32)
        idx1 = np.minimum(idx0 + 1, buf.size - 1)
        out = buf[idx0] + (buf[idx1] - buf[idx0]) * frac
        end_pos = self.pos + out_len * self.step
        consumed = int(end_pos)
        self.carry = buf[consumed:].copy()
        self.pos = float(end_pos - consumed)
        return out.astype(np.float32, copy=False)


class SpeechSegmenter:
    """Enerji (RMS) ve uyarlanan gürültü tabanlı konuşma bölütleyici (VAD)."""

    def __init__(
        self,
        sample_rate=TARGET_RATE,
        frame_ms=20,
        abs_min=0.0012,
        noise_mult=3.0,
        start_ms=40,
        end_silence_ms=500,
        pre_roll_ms=300,
        min_speech_ms=160,
        max_segment_ms=10000,
        trim_tail_ms=200,
        tail_pad_ms=100,
    ):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.abs_min = abs_min
        self.noise_mult = noise_mult
        self.min_speech_ms = min_speech_ms
        self.frame_len = max(1, round(sample_rate * frame_ms / 1000))
        self.start_frames = max(1, round(start_ms / frame_ms))
        self.end_silence_frames = max(1, round(end_silence_ms / frame_ms))
        self.pre_roll_frames = max(0, round(pre_roll_ms / frame_ms))
        self.max_segment_frames = max(1, round(max_segment_ms / frame_ms))
        self.trim_tail_frames = max(0, round(trim_tail_ms / frame_ms))
        self.tail_pad_frames = max(0, round(tail_pad_ms / frame_ms))
        self.reset()

    def reset(self):
        self.rest = np.zeros(0, dtype=np.float32)
        self.pre_roll = []
        self.segment = []
        self.onset = 0
        self.silence = 0
        self.speech_frames = 0
        self.noise_floor = 0.0004
        self.speaking = False
        self.level = 0.0
        self.threshold = self.abs_min

    def set_sensitivity(self, key):
        cfg = SENSITIVITIES.get(key)
        if not cfg:
            return
        self.abs_min = cfg["abs_min"]
        self.noise_mult = cfg["noise_mult"]
        self.threshold = max(self.abs_min, self.noise_floor * self.noise_mult)

    def push(self, chunk):
        arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return []
        buf = np.concatenate((self.rest, arr)) if self.rest.size else arr
        out = []
        i = 0
        n = buf.size
        while i + self.frame_len <= n:
            frame = buf[i:i + self.frame_len]
            i += self.frame_len
            seg = self._step_frame(frame)
            if seg is not None:
                out.append(seg)
        self.rest = buf[i:].copy() if i < n else np.zeros(0, dtype=np.float32)
        return out

    def flush(self):
        out = []
        if self.rest.size:
            seg = self._step_frame(self.rest)
            if seg is not None:
                out.append(seg)
        self.rest = np.zeros(0, dtype=np.float32)
        if self.segment:
            seg = self._finish(force=False)
            if seg is not None:
                out.append(seg)
        return out

    def _step_frame(self, frame):
        rms = float(np.sqrt(np.mean(frame * frame))) if frame.size else 0.0
        self.level = rms
        if not self.speaking:
            observed = min(rms, 0.01)
            if rms <= max(self.abs_min, self.noise_floor * 2.2):
                self.noise_floor = min(0.01, max(0.00015, 0.98 * self.noise_floor + 0.02 * observed))
        thr = max(self.abs_min, self.noise_floor * self.noise_mult)
        self.threshold = thr
        voiced = rms > thr

        if not self.speaking:
            self.pre_roll.append(frame.copy())
            if len(self.pre_roll) > self.pre_roll_frames + 1:
                self.pre_roll.pop(0)
            self.onset = (self.onset + 1) if voiced else 0
            if self.onset >= self.start_frames:
                self.speaking = True
                self.segment = list(self.pre_roll)
                self.pre_roll = []
                self.silence = 0
                self.speech_frames = self.onset
            return None

        self.segment.append(frame.copy())
        if voiced:
            self.silence = 0
            self.speech_frames += 1
        else:
            self.silence += 1

        if self.silence >= self.end_silence_frames:
            return self._finish(force=False)
        if len(self.segment) >= self.max_segment_frames:
            return self._finish(force=True)
        return None

    def _finish(self, force=False):
        frames = self.segment
        if not force and self.trim_tail_frames > 0:
            cut = 0
            for f in reversed(frames):
                if float(np.sqrt(np.mean(f * f))) > self.threshold:
                    break
                cut += 1
            cut = min(cut, self.trim_tail_frames)
            if cut > 0:
                frames = frames[:-cut]

        spoken_ms = self.speech_frames * self.frame_ms
        speech = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
        fade_n = min(speech.size, round(self.sample_rate * 0.005))
        if fade_n > 1:
            speech = speech.copy()
            speech[-fade_n:] *= np.linspace(1.0, 0.0, fade_n, endpoint=False, dtype=np.float32)
        pad_n = self.frame_len * self.tail_pad_frames
        merged = np.concatenate((speech, np.zeros(pad_n, dtype=np.float32))) if pad_n else speech
        carry = list(frames[-self.pre_roll_frames:]) if (force and frames and self.pre_roll_frames) else []

        self.segment = []
        self.speaking = False
        self.silence = 0
        self.onset = 0
        self.speech_frames = 0
        self.pre_roll = carry

        if spoken_ms < self.min_speech_ms or merged.size < self.sample_rate * (self.min_speech_ms / 1000.0):
            return None
        return merged.astype(np.float32, copy=False)


def _default_input_index():
    if not _SD_OK:
        return None
    try:
        raw = sd.default.device
        val = raw[0] if hasattr(raw, "__getitem__") else raw
        idx = int(val)
        return idx if idx >= 0 else None
    except Exception:
        return None


def list_input_devices():
    """Kullanılabilir Windows ses giriş (mikrofon) aygıtlarını listele (varsayılan ilk sırada)."""
    if not _SD_OK:
        return []
    try:
        devs = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception:
        return []

    default_idx = _default_input_index()
    items = []
    seen = set()
    seen_labels = set()
    # Önce sistem varsayılanını koy, sonra diğer temiz aygıtları ekle
    indices = ([default_idx] if default_idx is not None and 0 <= default_idx < len(devs) else []) + list(range(len(devs)))
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        d = devs[idx]
        if int(d.get("max_input_channels", 0)) <= 0:
            continue
        api_name = ""
        try:
            api_name = apis[int(d.get("hostapi", 0))].get("name", "")
        except Exception:
            pass
        # WDM-KS iç çekirdek cihazları yerine kullanıcı dostu MME / WASAPI / DirectSound tut
        if "WDM-KS" in api_name:
            continue
        name = str(d.get("name", f"Mikrofon #{idx}")).strip()
        is_def = (idx == default_idx)
        prefix = "Varsayılan: " if is_def else ""
        label = f"{prefix}{name}" + (f" ({api_name})" if api_name and not is_def else "")
        if label in seen_labels:
            label = f"{label} #{idx}"
        seen_labels.add(label)
        items.append({
            "index": idx,
            "name": name,
            "label": label,
            "samplerate": int(round(float(d.get("default_samplerate", TARGET_RATE) or TARGET_RATE))),
            "is_default": is_def,
        })
    return items


def _local_model_dir(models_dir=STT_MODELS_DIR):
    return os.path.join(models_dir, "whisper-large-v3-turbo")


def _model_files_present(model_dir):
    return os.path.isfile(os.path.join(model_dir, "model.bin")) and os.path.isfile(os.path.join(model_dir, "config.json"))


class NativeSTTController:
    """Tarayıcıdan tamamen bağımsız yerel mikrofon + faster-whisper STT yöneticisi."""

    def __init__(self, emit_cb, models_dir=STT_MODELS_DIR, repo_id=DEFAULT_STT_REPO):
        self._emit = emit_cb
        self.models_dir = models_dir
        self.repo_id = repo_id
        self._model = None
        self._model_device = ""
        self._lock = threading.Lock()
        self._dl_lock = threading.Lock()
        self._ctrl_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._run_id = 0
        self._active_stop_ev = None
        self._active_abort_ev = None
        self._active_pcm_q = None
        self._segmenter = SpeechSegmenter()
        self._sensitivity = "normal"

    def is_model_cached(self):
        return _model_files_present(_local_model_dir(self.models_dir))

    def set_sensitivity(self, key):
        if key in SENSITIVITIES:
            self._sensitivity = key
            self._segmenter.set_sensitivity(key)

    def ensure_model(self, run_id, is_stale):
        with self._lock:
            if self._model is not None:
                return self._model, self._model_device

        model_dir = _local_model_dir(self.models_dir)
        os.makedirs(self.models_dir, exist_ok=True)
        with self._dl_lock:
            if not _model_files_present(model_dir):
                self._emit({
                    "type": "progress",
                    "sid": run_id,
                    "message": "Yerel Türkçe STT modeli hazırlanıyor (~1.5 GB, ilk sefer)...",
                })
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo_id=self.repo_id,
                    local_dir=model_dir,
                )
        if is_stale():
            return None, ""

        ensure_cuda_dlls()
        from faster_whisper import WhisperModel

        model = None
        dev_label = "CPU"
        self._emit({"type": "progress", "sid": run_id, "message": "STT modeli belleğe yükleniyor..."})
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                model = WhisperModel(model_dir, device="cuda", compute_type="float16", local_files_only=True)
                dev_label = "GPU"
        except Exception:
            model = None
        if is_stale():
            return None, ""
        if model is None:
            threads = max(2, (os.cpu_count() or 4) // 2)
            model = WhisperModel(
                model_dir, device="cpu", compute_type="int8",
                cpu_threads=threads, local_files_only=True,
            )
            dev_label = "CPU"

        with self._lock:
            if self._model is None:
                self._model = model
                self._model_device = dev_label
            return self._model, self._model_device

    def start(self, run_id, sens="normal", device_index=None, is_stale=None):
        """Arka plan iş parçacığından çağrılır: modeli yükler, mikrofonu açar ve döngüyü yönetir."""
        if not _SD_OK:
            self._emit({
                "type": "done", "ok": False, "sid": run_id,
                "error": "sounddevice paketi yüklü değil (py -3.13 -m pip install sounddevice).",
            })
            return

        check_stale = is_stale or (lambda: run_id != self._run_id)
        stop_ev = threading.Event()
        abort_ev = threading.Event()
        pcm_q = queue.Queue(maxsize=128)
        with self._ctrl_lock:
            self._run_id = run_id
            self._active_stop_ev = stop_ev
            self._active_abort_ev = abort_ev
            self._active_pcm_q = pcm_q
            self._sensitivity = sens if sens in SENSITIVITIES else "normal"

        seg_cfg = SENSITIVITIES[self._sensitivity]
        segmenter = SpeechSegmenter(
            abs_min=seg_cfg["abs_min"],
            noise_mult=seg_cfg["noise_mult"],
        )
        self._segmenter = segmenter

        try:
            model, dev_label = self.ensure_model(run_id, check_stale)
        except Exception as e:
            if check_stale():
                return
            self._emit({"type": "done", "ok": False, "cancelled": False, "sid": run_id, "error": f"STT model yüklenemedi: {e}"})
            return

        if model is None or check_stale() or abort_ev.is_set():
            self._emit({"type": "done", "ok": False, "cancelled": True, "sid": run_id})
            return

        # Mikrofon akışı ayarlarını seç: önceki akış kapandıktan sonra aç
        dev_arg = device_index if device_index is not None else None
        infer_q = queue.Queue(maxsize=16)

        with self._stream_lock:
            if check_stale() or abort_ev.is_set():
                self._emit({"type": "done", "ok": False, "cancelled": True, "sid": run_id})
                return

            actual_rate = TARGET_RATE
            channels = 1
            try:
                sd.check_input_settings(device=dev_arg, channels=1, samplerate=TARGET_RATE, dtype="float32")
            except Exception:
                try:
                    def_in = _default_input_index()
                    d_info = sd.query_devices(dev_arg if dev_arg is not None else def_in, "input")
                    actual_rate = int(round(float(d_info.get("default_samplerate", 48000) or 48000)))
                    max_ch = int(d_info.get("max_input_channels", 1) or 1)
                    try:
                        sd.check_input_settings(device=dev_arg, channels=1, samplerate=actual_rate, dtype="float32")
                        channels = 1
                    except Exception:
                        channels = min(2, max(1, max_ch))
                except Exception:
                    actual_rate = 48000
                    channels = 1

            resampler = LinearResampler(actual_rate, TARGET_RATE) if abs(actual_rate - TARGET_RATE) > 1 else None

            def audio_cb(indata, frames, _time_info, status):
                if stop_ev.is_set() or abort_ev.is_set():
                    return
                try:
                    mono = indata[:, 0].copy() if indata.shape[1] == 1 else np.mean(indata, axis=1).astype(np.float32)
                    pcm_q.put_nowait(mono)
                except queue.Full:
                    pass

            last_text = ""
            last_at = 0.0

            def infer_worker():
                nonlocal last_text, last_at
                while True:
                    item = infer_q.get()
                    if item is None:
                        break
                    if abort_ev.is_set() or check_stale():
                        continue
                    dur = item.size / float(TARGET_RATE)
                    self._emit({"type": "state", "state": "transcribing", "detail": f"Yazıya dökülüyor ({dur:.1f}s)...", "sid": run_id})
                    had_err = False
                    try:
                        # AGC olmayan ham Windows mikrofonlarında düşük seviyeyi Whisper için güvenle normalize et
                        seg_rms = float(np.sqrt(np.mean(item * item))) if item.size else 0.0
                        seg_peak = float(np.max(np.abs(item))) if item.size else 0.0
                        audio_in = item
                        if seg_rms > 1e-5 and seg_peak > 1e-4 and seg_rms < 0.06:
                            gain = min(20.0, 0.06 / seg_rms, 0.6 / seg_peak)
                            if gain > 1.2:
                                audio_in = np.clip(item * gain, -0.95, 0.95).astype(np.float32)
                        segments, _info = model.transcribe(
                            audio_in,
                            language="tr",
                            task="transcribe",
                            beam_size=1,
                            condition_on_previous_text=False,
                            vad_filter=False,
                        )
                        raw = " ".join((seg.text or "").strip() for seg in segments).strip()
                        now_ts = time.monotonic()
                        clean = filter_transcript(raw, last_text=last_text, last_at=last_at, now=now_ts)
                        if clean:
                            last_text = clean
                            last_at = now_ts
                            self._emit({"type": "text", "text": clean, "sid": run_id})
                    except Exception as e:
                        had_err = True
                        self._emit({"type": "error", "message": f"Yazıya dökme hatası: {e}", "sid": run_id})
                    if not had_err and not stop_ev.is_set() and not abort_ev.is_set():
                        self._emit({"type": "state", "state": "listening", "sid": run_id})

            inf_thread = threading.Thread(target=infer_worker, daemon=True)
            inf_thread.start()

            stream = None
            try:
                stream = sd.InputStream(
                    device=dev_arg,
                    channels=channels,
                    samplerate=actual_rate,
                    dtype="float32",
                    blocksize=max(512, int(actual_rate * 0.064)),
                    callback=audio_cb,
                )
                stream.start()
            except Exception as e:
                infer_q.put(None)
                err_s = str(e)
                hint = (
                    "Mikrofon açılamadı. Windows Gizlilik -> Mikrofon ayarlarında masaüstü uygulamalarına izin verin."
                    if ("access" in err_s.lower() or "denied" in err_s.lower() or "unanticipated" in err_s.lower())
                    else f"Mikrofon akışı açılamadı: {err_s[:140]}"
                )
                self._emit({"type": "done", "ok": False, "cancelled": False, "sid": run_id, "error": hint})
                return

            if check_stale() or abort_ev.is_set():
                stop_ev.set()
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                infer_q.put(None)
                return

            self._emit({"type": "listening", "sid": run_id, "device": dev_label})

            zero_blocks = 0
            had_signal = False
            last_lvl_emit = 0.0
            last_speech_state = False
            min_emit_samples = int(TARGET_RATE * 0.25)

            try:
                while not stop_ev.is_set() and not abort_ev.is_set() and not check_stale():
                    try:
                        chunk = pcm_q.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        break
                    if resampler is not None:
                        chunk = resampler.process(chunk)
                        if chunk.size == 0:
                            continue
                    if not had_signal:
                        if float(np.max(np.abs(chunk))) > 1e-7:
                            had_signal = True
                            zero_blocks = 0
                        else:
                            zero_blocks += 1
                            if zero_blocks == 35:
                                self._emit({
                                    "type": "state", "state": "no_signal",
                                    "detail": "Mikrofondan ses verisi gelmiyor — başka bir mikrofon seçip deneyin.",
                                    "sid": run_id,
                                })
                    for sentence in segmenter.push(chunk):
                        if sentence.size >= min_emit_samples:
                            try:
                                infer_q.put_nowait(sentence)
                            except queue.Full:
                                pass
                    now_m = time.monotonic()
                    if (now_m - last_lvl_emit) >= 0.10:
                        last_lvl_emit = now_m
                        self._emit({
                            "type": "level",
                            "level": segmenter.level,
                            "threshold": segmenter.threshold,
                            "speaking": segmenter.speaking,
                            "sid": run_id,
                        })
                    if segmenter.speaking and not last_speech_state:
                        last_speech_state = True
                        self._emit({"type": "state", "state": "speech", "sid": run_id})
                    elif not segmenter.speaking:
                        last_speech_state = False
            finally:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

        # Kuyrukta kalan son cümleyi yazıya dök (iptal/abort yoksa)
        if not abort_ev.is_set() and not check_stale():
            while not pcm_q.empty():
                try:
                    c = pcm_q.get_nowait()
                    if c is None:
                        continue
                    if resampler is not None:
                        c = resampler.process(c)
                    for sentence in segmenter.push(c):
                        if sentence.size >= min_emit_samples:
                            infer_q.put(sentence)
                except queue.Empty:
                    break
            for sentence in segmenter.flush():
                if sentence.size >= min_emit_samples:
                    infer_q.put(sentence)
            infer_q.put(None)
            inf_thread.join(timeout=8.0)
            self._emit({"type": "done", "ok": True, "cancelled": False, "sid": run_id})
        else:
            infer_q.put(None)

    def stop(self):
        with self._ctrl_lock:
            if self._active_stop_ev is not None:
                self._active_stop_ev.set()
            q = self._active_pcm_q
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception:
                pass

    def abort(self):
        with self._ctrl_lock:
            self._run_id += 1
            if self._active_abort_ev is not None:
                self._active_abort_ev.set()
            if self._active_stop_ev is not None:
                self._active_stop_ev.set()
            q = self._active_pcm_q
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception:
                pass
