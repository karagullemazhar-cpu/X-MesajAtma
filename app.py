#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-MesajAtma - canli mesaj sayaci (tek dosya, Flask + SQLite)

Ne yapar?
  Kullanicilardan gelen her mesaji kaydeder ve http://127.0.0.1:5077 adresinde
  canli bir panelde 4 sayi gosterir: toplam mesaj, bugunku mesaj, kac kisi
  yazdi, kisi basina ortalama mesaj.

Kendi uygulamanla baglanti (3 yol):
  1) POST http://127.0.0.1:5077/api/mesaj
     {"kullanici": "ali", "mesaj": "merhaba", "kanal": "uygulama"}
  2) Tarayici/webhook: http://127.0.0.1:5077/api/mesaj?kullanici=ali&mesaj=merhaba
  3) Python: requests.post(...)  (ornek_gonder.py dosyasina bak)

Gizli bilgi yoktur: hicbir API anahtari gerektirmez. Istersen .env icine
MESAJ_ANAHTARI=yaz ve panel ile API'yi sifreli hale getir.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request

# ---------------------------------------------------------------- ayarlar

KOK = Path(__file__).resolve().parent


def env_yukle() -> None:
    """.env dosyasi varsa oku (ek paket gerekmesin diye basit okuyucu)."""
    dosya = KOK / ".env"
    if not dosya.exists():
        return
    for satir in dosya.read_text(encoding="utf-8", errors="ignore").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, deger = satir.split("=", 1)
        anahtar = anahtar.strip()
        deger = deger.strip().strip('"').strip("'")
        if anahtar and anahtar not in os.environ:
            os.environ[anahtar] = deger


env_yukle()

PORT = int(os.environ.get("PORT", "5077"))
HOST = os.environ.get("HOST", "127.0.0.1")          # guvenli varsayilan: sadece bu bilgisayar
ANAHTAR = os.environ.get("MESAJ_ANAHTARI", "").strip()  # bos ise sifre yok
VERITABANI = Path(os.environ.get("XMA_DB", str(KOK / "mesajlar.db")))
MAX_UZUNLUK = 2000

app = Flask(__name__)


# ---------------------------------------------------------------- veritabani

def baglan() -> sqlite3.Connection:
    con = sqlite3.connect(VERITABANI, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def kur() -> None:
    con = baglan()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mesajlar (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici TEXT    NOT NULL,
                mesaj     TEXT    NOT NULL DEFAULT '',
                kanal     TEXT    NOT NULL DEFAULT 'uygulama',
                zaman     TEXT    NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS i_zaman ON mesajlar(zaman)")
        con.execute("CREATE INDEX IF NOT EXISTS i_kullanici ON mesajlar(kullanici)")
        con.commit()
    finally:
        con.close()


def simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- yardimcilar

def anahtar_dogru() -> bool:
    if not ANAHTAR:
        return True
    gelen = request.headers.get("X-Anahtar") or request.args.get("anahtar") or ""
    if request.method == "POST" and not gelen:
        veri = request.get_json(silent=True) or {}
        if isinstance(veri, dict):
            gelen = str(veri.get("anahtar") or "")
    return gelen.strip() == ANAHTAR


def mesaj_ekle(kullanici: str, mesaj: str, kanal: str) -> dict:
    kullanici = (kullanici or "").strip() or "bilinmeyen"
    mesaj = (mesaj or "").strip()[:MAX_UZUNLUK]
    kanal = (kanal or "uygulama").strip()[:40] or "uygulama"
    zaman = simdi()
    con = baglan()
    try:
        cur = con.execute(
            "INSERT INTO mesajlar (kullanici, mesaj, kanal, zaman) VALUES (?,?,?,?)",
            (kullanici, mesaj, kanal, zaman),
        )
        con.commit()
        return {"id": cur.lastrowid, "kullanici": kullanici, "zaman": zaman}
    finally:
        con.close()


def ozet_hesapla(sinir: int = 12) -> dict:
    bugun = datetime.now().strftime("%Y-%m-%d")
    bir_saat_once = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    con = baglan()
    try:
        toplam = con.execute("SELECT COUNT(*) c FROM mesajlar").fetchone()["c"]
        bugun_adet = con.execute(
            "SELECT COUNT(*) c FROM mesajlar WHERE substr(zaman,1,10)=?", (bugun,)
        ).fetchone()["c"]
        kisi = con.execute("SELECT COUNT(DISTINCT kullanici) c FROM mesajlar").fetchone()["c"]
        son_saat = con.execute(
            "SELECT COUNT(*) c FROM mesajlar WHERE zaman>=?", (bir_saat_once,)
        ).fetchone()["c"]
        son = con.execute("SELECT MAX(zaman) z FROM mesajlar").fetchone()["z"]
        kullanicilar = [
            dict(r)
            for r in con.execute(
                """
                SELECT kullanici AS ad, COUNT(*) AS adet, MAX(zaman) AS son
                FROM mesajlar GROUP BY kullanici
                ORDER BY adet DESC, son DESC LIMIT ?
                """,
                (sinir,),
            )
        ]
        son_mesajlar = [
            dict(r)
            for r in con.execute(
                """
                SELECT kullanici, mesaj, kanal, zaman FROM mesajlar
                ORDER BY id DESC LIMIT ?
                """,
                (sinir,),
            )
        ]
    finally:
        con.close()

    ortalama = round(toplam / kisi, 1) if kisi else 0.0
    return {
        "toplam": toplam,
        "bugun": bugun_adet,
        "kullanici": kisi,
        "kullanici_basina": ortalama,
        "son_saat": son_saat,
        "son_mesaj_zamani": son,
        "kullanicilar": kullanicilar,
        "son_mesajlar": son_mesajlar,
        "guncellendi": datetime.now().strftime("%H:%M:%S"),
    }


# ---------------------------------------------------------------- API

@app.get("/api/ozet")
def api_ozet():
    if not anahtar_dogru():
        return jsonify({"hata": "anahtar gecersiz"}), 401
    return jsonify(ozet_hesapla())


@app.get("/api/durum")
def api_durum():
    return jsonify({"durum": "calisiyor", "port": PORT, "surum": "1.0.0"})


@app.route("/api/mesaj", methods=["POST", "GET"])
def api_mesaj():
    if not anahtar_dogru():
        return jsonify({"hata": "anahtar gecersiz"}), 401

    if request.method == "POST":
        veri = request.get_json(silent=True)
        if not isinstance(veri, dict):
            veri = request.form.to_dict() if request.form else {}
        kullanici = str(veri.get("kullanici") or veri.get("user") or veri.get("kimden") or "")
        mesaj = str(veri.get("mesaj") or veri.get("message") or veri.get("metin") or "")
        kanal = str(veri.get("kanal") or veri.get("channel") or "uygulama")
    else:
        kullanici = request.args.get("kullanici", "")
        mesaj = request.args.get("mesaj", "")
        kanal = request.args.get("kanal", "uygulama")

    if not kullanici:
        return jsonify({"hata": "kullanici alani zorunlu"}), 400

    kayit = mesaj_ekle(kullanici, mesaj, kanal)
    return jsonify({"ok": True, **kayit}), 201


@app.post("/api/demo")
def api_demo():
    """Paneldeki 'Test mesaji' dugmesi: sayilarin nasil aktigini gosterir."""
    if not anahtar_dogru():
        return jsonify({"hata": "anahtar gecersiz"}), 401
    isimler = ["ali", "ayse", "mehmet", "zeynep", "can"]
    ornek = [
        "Merhaba, bilgi alabilir miyim?",
        "Fiyatlar ne kadar?",
        "Tesekkurler, cok yardimci oldunuz.",
        "Siparisim ne zaman gelir?",
        "Bir sorun var, yardim eder misiniz?",
    ]
    gonderilen = 0
    for i in range(5):
        mesaj_ekle(isimler[i % len(isimler)], ornek[i % len(ornek)], "demo")
        gonderilen += 1
    return jsonify({"ok": True, "eklenen": gonderilen}), 201


@app.post("/api/temizle")
def api_temizle():
    if not anahtar_dogru():
        return jsonify({"hata": "anahtar gecersiz"}), 401
    con = baglan()
    try:
        con.execute("DELETE FROM mesajlar")
        con.commit()
    finally:
        con.close()
    return jsonify({"ok": True})


@app.get("/api/mesajlar.csv")
def api_csv():
    if not anahtar_dogru():
        return jsonify({"hata": "anahtar gecersiz"}), 401
    con = baglan()
    try:
        satirlar = con.execute(
            "SELECT id, kullanici, mesaj, kanal, zaman FROM mesajlar ORDER BY id"
        ).fetchall()
    finally:
        con.close()

    tampon = io.StringIO()
    yazici = csv.writer(tampon)
    yazici.writerow(["id", "kullanici", "mesaj", "kanal", "zaman"])
    for r in satirlar:
        yazici.writerow([r["id"], r["kullanici"], r["mesaj"], r["kanal"], r["zaman"]])

    return Response(
        "\ufeff" + tampon.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=mesajlar.csv"},
    )


# ---------------------------------------------------------------- panel

@app.get("/")
def panel():
    return Response(PANEL_HTML.replace("{{PORT}}", str(PORT)), mimetype="text/html; charset=utf-8")


PANEL_HTML = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X-MesajAtma - Canli Mesaj Paneli</title>
<style>
  :root{
    --bg:#0d1117; --kart:#161b22; --cizgi:#262d38; --yazi:#e6edf3;
    --soluk:#8b949e; --yesil:#3fb950; --mavi:#58a6ff; --mor:#bc8cff; --turuncu:#f0883e;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--yazi);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{display:flex;align-items:center;gap:14px;padding:18px 26px;border-bottom:1px solid var(--cizgi);
         flex-wrap:wrap}
  h1{font-size:19px;margin:0;font-weight:650;letter-spacing:.2px}
  .nokta{width:9px;height:9px;border-radius:50%;background:var(--yesil);
         box-shadow:0 0 0 0 rgba(63,185,80,.7);animation:nabiz 1.8s infinite}
  @keyframes nabiz{70%{box-shadow:0 0 0 9px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
  .canli{color:var(--yesil);font-size:13px;font-weight:600}
  .saat{margin-left:auto;color:var(--soluk);font-size:13px}
  main{padding:22px 26px 40px;max-width:1180px;margin:0 auto}
  .kutular{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
  .kutu{background:var(--kart);border:1px solid var(--cizgi);border-radius:14px;padding:18px 20px;
        position:relative;overflow:hidden}
  .kutu::after{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--mavi)}
  .kutu.b::after{background:var(--yesil)} .kutu.c::after{background:var(--mor)} .kutu.d::after{background:var(--turuncu)}
  .etiket{font-size:12.5px;color:var(--soluk);text-transform:uppercase;letter-spacing:.7px;font-weight:600}
  .sayi{font-size:40px;font-weight:700;margin-top:8px;line-height:1.1;font-variant-numeric:tabular-nums}
  .alt{font-size:12.5px;color:var(--soluk);margin-top:6px}
  .izgara{display:grid;gap:14px;grid-template-columns:1.15fr .85fr;margin-top:20px}
  @media (max-width:860px){.izgara{grid-template-columns:1fr}}
  .panel{background:var(--kart);border:1px solid var(--cizgi);border-radius:14px;padding:0;overflow:hidden}
  .panel h2{font-size:14px;margin:0;padding:15px 18px;border-bottom:1px solid var(--cizgi);
            font-weight:650;display:flex;align-items:center;gap:8px}
  .panel h2 span{color:var(--soluk);font-weight:500;font-size:12.5px;margin-left:auto}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{text-align:left;padding:10px 18px;border-bottom:1px solid #1e242c}
  th{color:var(--soluk);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px;font-weight:600}
  tr:last-child td{border-bottom:none}
  td.ad{font-weight:600}
  td.sayi{text-align:right;font-variant-numeric:tabular-nums;color:var(--mavi);font-weight:650}
  .satir{display:flex;gap:10px;align-items:flex-start;padding:11px 18px;border-bottom:1px solid #1e242c}
  .satir:last-child{border-bottom:none}
  .kim{font-weight:650;font-size:13px;color:var(--mor);min-width:74px}
  .metin{font-size:13.5px;color:#c9d1d9;flex:1;word-break:break-word}
  .zaman{font-size:11.5px;color:var(--soluk);white-space:nowrap}
  .bos{padding:26px 18px;color:var(--soluk);font-size:13.5px;text-align:center}
  .dugme{background:#21262d;color:var(--yazi);border:1px solid #30363d;border-radius:9px;
         padding:9px 15px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit}
  .dugme:hover{background:#2d333b;border-color:#484f58}
  .dugme.yesil{background:#238636;border-color:#2ea043}
  .dugme.yesil:hover{background:#2ea043}
  .arac{display:flex;gap:9px;flex-wrap:wrap;margin-top:20px}
  code{background:#0d1117;border:1px solid var(--cizgi);border-radius:6px;padding:2px 6px;
       font-size:12.5px;color:#79c0ff}
  .ipucu{margin-top:18px;color:var(--soluk);font-size:12.5px;line-height:1.7}
</style>
</head>
<body>
<header>
  <span class="nokta"></span>
  <span class="canli">CANLI</span>
  <h1>X-MesajAtma</h1>
  <span class="saat" id="saat">--:--:--</span>
</header>

<main>
  <div class="kutular">
    <div class="kutu"><div class="etiket">Toplam mesaj</div><div class="sayi" id="toplam">0</div>
      <div class="alt">kayitli tum mesajlar</div></div>
    <div class="kutu b"><div class="etiket">Bugun</div><div class="sayi" id="bugun">0</div>
      <div class="alt">son 1 saatte <b id="son_saat">0</b></div></div>
    <div class="kutu c"><div class="etiket">Kac kisi yazdi</div><div class="sayi" id="kullanici">0</div>
      <div class="alt">farkli kullanici</div></div>
    <div class="kutu d"><div class="etiket">Kisi basina</div><div class="sayi" id="ortalama">0</div>
      <div class="alt">ortalama mesaj</div></div>
  </div>

  <div class="izgara">
    <div class="panel">
      <h2>Kullanicilar <span>mesaj sayisina gore</span></h2>
      <table>
        <thead><tr><th>Kullanici</th><th style="text-align:right">Mesaj</th><th>Son mesaj</th></tr></thead>
        <tbody id="kullanicilar"><tr><td colspan="3" class="bos">Henuz mesaj yok</td></tr></tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Son mesajlar <span>canli akis</span></h2>
      <div id="son_mesajlar"><div class="bos">Henuz mesaj yok</div></div>
    </div>
  </div>

  <div class="arac">
    <button class="dugme yesil" onclick="demo()">Test mesaji gonder (5 adet)</button>
    <button class="dugme" onclick="yukle()">Yenile</button>
    <button class="dugme" onclick="location.href='/api/mesajlar.csv' + (qs ? '?' + qs : '')">CSV indir</button>
    <button class="dugme" onclick="sifirla()">Verileri sifirla</button>
  </div>

  <div class="ipucu">
    Kendi uygulamandan mesaj gondermek icin:<br>
    <code>POST http://127.0.0.1:{{PORT}}/api/mesaj</code>
    &nbsp;govde: <code>{"kullanici":"ali","mesaj":"merhaba","kanal":"uygulama"}</code><br>
    Tarayici veya webhook ile: <code>http://127.0.0.1:{{PORT}}/api/mesaj?kullanici=ali&amp;mesaj=merhaba</code>
  </div>
</main>

<script>
const $ = id => document.getElementById(id);
const say = n => new Intl.NumberFormat('tr-TR').format(n ?? 0);
const ANAHTAR = new URLSearchParams(location.search).get('anahtar') || '';
const qs = ANAHTAR ? ('anahtar=' + encodeURIComponent(ANAHTAR)) : '';

function kacis(s){
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function yukle(){
  try{
    const c = await fetch('/api/ozet' + (qs ? '?' + qs : ''), {cache:'no-store'});
    if(c.status === 401){
      $('saat').textContent = 'sifre gerekli';
      if(!document.getElementById('sifre-uyari')){
        document.querySelector('main').insertAdjacentHTML('afterbegin',
          '<div id="sifre-uyari" style="background:#3d1d1d;border:1px solid #6e2b2b;border-radius:12px;' +
          'padding:14px 18px;margin-bottom:18px;font-size:13.5px;line-height:1.7">' +
          'Bu panel sifreli. Adresin sonuna <code>?anahtar=kelimen</code> ekleyin. ' +
          'Ornek: <code>http://127.0.0.1:{{PORT}}/?anahtar=kelimen</code></div>');
      }
      return;
    }
    if(!c.ok) throw new Error('cevap yok');
    const v = await c.json();

    $('toplam').textContent    = say(v.toplam);
    $('bugun').textContent     = say(v.bugun);
    $('kullanici').textContent = say(v.kullanici);
    $('ortalama').textContent  = String(v.kullanici_basina ?? 0).replace('.', ',');
    $('son_saat').textContent  = say(v.son_saat);
    $('saat').textContent      = v.guncellendi;

    const k = v.kullanicilar || [];
    $('kullanicilar').innerHTML = k.length
      ? k.map(x => `<tr><td class="ad">${kacis(x.ad)}</td><td class="sayi">${say(x.adet)}</td>
                    <td class="zaman">${kacis((x.son || '').slice(11))}</td></tr>`).join('')
      : '<tr><td colspan="3" class="bos">Henuz mesaj yok</td></tr>';

    const s = v.son_mesajlar || [];
    $('son_mesajlar').innerHTML = s.length
      ? s.map(x => `<div class="satir">
          <span class="kim">${kacis(x.kullanici)}</span>
          <span class="metin">${kacis(x.mesaj) || '<i>(bos mesaj)</i>'}</span>
          <span class="zaman">${kacis((x.zaman || '').slice(11))}</span>
        </div>`).join('')
      : '<div class="bos">Henuz mesaj yok</div>';
  }catch(e){
    $('saat').textContent = 'baglanti yok';
  }
}

async function demo(){
  await fetch('/api/demo' + (qs ? '?' + qs : ''), {method:'POST'});
  yukle();
}

async function sifirla(){
  if(!confirm('Tum mesaj kayitlari silinecek. Emin misin?')) return;
  await fetch('/api/temizle' + (qs ? '?' + qs : ''), {method:'POST'});
  yukle();
}

yukle();
setInterval(yukle, 2000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- calistir

def tarayici_ac() -> None:
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:
        pass


def main() -> None:
    kur()
    print("")
    print("  X-MesajAtma calisiyor")
    print(f"  Panel:  http://127.0.0.1:{PORT}")
    print(f"  Kayit:  {VERITABANI}")
    print("  Kapatmak icin bu pencereyi kapatin veya Ctrl+C basin.")
    print("")
    if os.environ.get("XMA_AC") == "1":
        threading.Timer(1.5, tarayici_ac).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
