#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ornek_gonder.py - X-MesajAtma'ya ornek mesaj gonderme

Amac: kendi uygulaman mesaj aldiginda ne yapmasi gerektigini gostermek.
Kullanim:
    python ornek_gonder.py
    python ornek_gonder.py 20        (20 mesaj gonder)

Sadece Python'un kendi kutuphanesini kullanir; ek paket gerekmez.
"""

import json
import random
import sys
import urllib.request

ADRES = "http://127.0.0.1:5077/api/mesaj"

KISILER = ["ali", "ayse", "mehmet", "zeynep", "can", "elif"]
METINLER = [
    "Merhaba, bilgi alabilir miyim?",
    "Fiyat listesi var mi?",
    "Siparisim ne zaman gelir?",
    "Tesekkurler, cok yardimci oldunuz.",
    "Bir sorun var, yardim eder misiniz?",
    "Stokta var mi acaba?",
]


def gonder(kullanici: str, mesaj: str, kanal: str = "ornek") -> dict:
    govde = json.dumps(
        {"kullanici": kullanici, "mesaj": mesaj, "kanal": kanal}
    ).encode("utf-8")
    istek = urllib.request.Request(
        ADRES, data=govde, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(istek, timeout=10) as cevap:
        return json.loads(cevap.read().decode("utf-8"))


def main() -> None:
    adet = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    print(f"{adet} ornek mesaj gonderiliyor... -> {ADRES}")
    for _ in range(adet):
        try:
            sonuc = gonder(random.choice(KISILER), random.choice(METINLER))
            print(f"  eklendi: {sonuc.get('kullanici')} (#{sonuc.get('id')})")
        except Exception as hata:  # noqa: BLE001
            print(f"  HATA: {hata}")
            print("  Panel acik mi? Once BASLAT.bat / baslat.sh calistirin.")
            return
    print("")
    print("Panelde sayilarin arttigini gorebilirsin: http://127.0.0.1:5077")


if __name__ == "__main__":
    main()
