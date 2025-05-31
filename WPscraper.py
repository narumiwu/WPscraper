#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import sys
import argparse
import logging
import requests
from bs4 import BeautifulSoup

# Jika ingin menggunakan modul googlesearch‐python, pastikan sudah terinstall:
#   pip install googlesearch-python
# Jika import ini gagal, skrip akan langsung keluar dengan pesan error.
try:
    from googlesearch import search
except ImportError:
    print("[ERROR] Modul googlesearch tidak ditemukan. Pastikan Anda telah menginstall 'googlesearch-python'.")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
#   Konfigurasi logging sederhana
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)


# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: fetch_and_extract_text
#    Mengunjungi URL dan mengembalikan teks bersih (plain text) dari <body>.
#    Jika gagal request atau parsing, kembalikan string kosong.
# ──────────────────────────────────────────────────────────────────────────────
def fetch_and_extract_text(url: str, timeout: float = 10.0) -> str:
    """
    Mengambil konten HTML dari `url`, lalu mengekstrak teks yang ada di dalam
    tag <body> (menghapus <script>, <style>, dan <noscript>).
    Jika gagal (timeout, status != 200, dsb.), kembalikan string kosong.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except Exception as e:
        logging.warning(f"Gagal mengambil URL `{url}`: {e}")
        return ""

    # Parse HTML
    soup = BeautifulSoup(resp.text, "html.parser")
    # Hapus elemen yang tidak diinginkan
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = soup.find("body")
    if not body:
        return ""

    # Ambil teks, normalisasi whitespace
    text = body.get_text(separator="\n", strip=True)
    return text


# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: get_wp_targets
#    Mencari situs WordPress di Google dengan beberapa dork, lalu
#    mengembalikan daftar URL domain unik hingga mencapai `limit`.
# ──────────────────────────────────────────────────────────────────────────────
def get_wp_targets(site_domain: str, total_limit: int, per_dork_limit: int, delay_between: float) -> list:
    """
    Mengumpulkan URL domain situs WordPress di dalam `site_domain` (misal: or.id),
    menggunakan beberapa dork berbeda. 
    - total_limit: max total URL unik yang diinginkan.
    - per_dork_limit: hasil maks per dork (Google Search).
    - delay_between: jeda (detik) antara satu panggilan Google ke berikutnya.
    """
    # Daftar dork‐dork WordPress paling umum:
    dorks = [
        f'inurl:wp-content site:{site_domain}',
        f'inurl:"/wp-content/themes/" site:{site_domain}',
        f'inurl:readme.html site:{site_domain}',
        f'"Powered by WordPress" site:{site_domain}',
        f'intitle:"Just another WordPress site" site:{site_domain}'
    ]

    found_urls = set()
    for dork in dorks:
        logging.info(f"🔍 Mencari dengan dork: {dork!r}")
        count = 0
        try:
            # Modul `search(...)` mengembalikan generator/iterator yang menghasilkan URL
            for url in search(dork, num_results=per_dork_limit):
                # Ekstrak domain root (misal: https://contoh.or.id)
                m = re.match(r"https?://[^/]+", url)
                if m:
                    domain_root = m.group(0)
                    found_urls.add(domain_root)
                count += 1
                if count >= per_dork_limit:
                    break
                time.sleep(delay_between)
        except Exception as e:
            logging.error(f"  Gagal saat memanggil Google Search untuk dork `{dork}`: {e}")
            # Lanjutkan ke dork berikutnya
            continue

        # Jika sudah mencapai jumlah total_limit, hentikan loop dork
        if len(found_urls) >= total_limit:
            break

        # Istirahat sejenak (sudah ada delay_between di dalam loop, tapi menambahkan ekstra delay)
        time.sleep(delay_between)

    # Kembalikan sebagai list, di‐slice hingga total_limit
    result_list = list(found_urls)[:total_limit]
    logging.info(f"✅ Total URL unik yang dikumpulkan: {len(result_list)} (limit={total_limit})")
    return result_list


# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi utama (main)
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Scrape konten WordPress dari Google (multi‐dork) dan simpan ke file .txt"
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Top-level domain atau sub-domain (contoh: or.id atau example.com)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Jumlah maksimum total situs unik WordPress yang ingin diambil (default: 30)."
    )
    parser.add_argument(
        "--per-dork",
        type=int,
        default=10,
        help="Maks hasil per dork Google (default: 10)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Jeda (detik) antara setiap panggilan Google Search (default: 1.0)."
    )
    parser.add_argument(
        "--timeout-fetch",
        type=float,
        default=8.0,
        help="Timeout (detik) untuk setiap request HTTP saat fetch konten (default: 8.0)."
    )
    parser.add_argument(
        "--output",
        default="wp_sites_text.txt",
        help="Nama file keluaran (default: wp_sites_text.txt)."
    )
    args = parser.parse_args()

    domain = args.domain
    total_limit = args.limit
    per_dork_limit = args.per_dork
    delay_between = args.delay
    timeout_fetch = args.timeout_fetch
    output_file = args.output

    logging.info(f"🚀 Mulai proses: domain={domain!r}, total_limit={total_limit}, per_dork={per_dork_limit}")
    # 1) Kumpulkan daftar target WordPress
    targets = get_wp_targets(domain, total_limit, per_dork_limit, delay_between)
    if not targets:
        logging.error("❌ Tidak ada target WordPress yang ditemukan. Proses dihentikan.")
        sys.exit(0)

    # 2) Buka file output untuk ditulis
    try:
        outf = open(output_file, "w", encoding="utf-8")
    except Exception as e:
        logging.error(f"Gagal membuka file `{output_file}` untuk ditulis: {e}")
        sys.exit(1)

    # 3) Ambil konten setiap situs dan simpan ke file
    for idx, site_url in enumerate(targets, start=1):
        logging.info(f"[{idx}/{len(targets)}] Fetch teks dari: {site_url}")
        page_text = fetch_and_extract_text(site_url, timeout=timeout_fetch)
        if page_text:
            # Tulis header URL
            outf.write(f"--- URL: {site_url}\n")
            outf.write(page_text + "\n\n")
            outf.write(("=" * 80) + "\n\n")
        else:
            logging.warning(f"   (⚠️) Tidak ada teks yang berhasil diambil dari: {site_url}")
        # Jeda sebentar agar tidak mem‐spam
        time.sleep(delay_between)

    outf.close()
    logging.info(f"✅ Selesai. Semua hasil disimpan di `{output_file}`.")


if __name__ == "__main__":
    main()
