#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import sys
import argparse
import logging
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Set

# ──────────────────────────────────────────────────────────────────────────────
#   Google Custom Search API Credentials (ganti dengan milik Anda)
# ──────────────────────────────────────────────────────────────────────────────
API_KEY = "AIzaSyCUaVp0gWKw1B5FmFiplAXl-gkwQEr_rVg"
CX_ID   = "c680430dddc14447"

# ──────────────────────────────────────────────────────────────────────────────
#  File untuk menyimpan daftar domain yang sudah pernah di‐scrap
# ──────────────────────────────────────────────────────────────────────────────
SCANNED_FILE = Path(".wpscraper_scanned")

# ──────────────────────────────────────────────────────────────────────────────
#   Konfigurasi logging sederhana
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: baca daftar domain yang sudah disimpan
# ──────────────────────────────────────────────────────────────────────────────
def read_scanned() -> Set[str]:
    if SCANNED_FILE.exists():
        return {line.strip() for line in SCANNED_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    return set()

# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: tambahkan satu domain ke file scanned
# ──────────────────────────────────────────────────────────────────────────────
def append_scanned(domain: str) -> None:
    with SCANNED_FILE.open("a", encoding="utf-8") as f:
        f.write(domain + "\n")

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

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = soup.find("body")
    if not body:
        return ""

    text = body.get_text(separator="\n", strip=True)
    return text

# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: get_wp_targets_cse
#    Mencari situs WordPress di Google Custom Search API dengan beberapa dork,
#    lalu mengembalikan daftar URL domain unik hingga mencapai `total_limit`.
# ──────────────────────────────────────────────────────────────────────────────
def get_wp_targets_cse(site_domain: str,
                       total_limit: int,
                       per_dork_limit: int,
                       delay_between: float) -> list:
    """
    Mengumpulkan URL root domain situs WordPress di dalam `site_domain` (misal: or.id),
    menggunakan beberapa dork berbeda lewat Google Custom Search JSON API.
    - total_limit: batas total URL unik yang diinginkan.
    - per_dork_limit: batas hasil unik per dork.
    - delay_between: jeda (detik) antara panggilan API.
    """
    dorks = [
        f'inurl:wp-content site:{site_domain}',
        f'inurl:"/wp-content/themes/" site:{site_domain}',
        f'inurl:readme.html site:{site_domain}',
        f'"Powered by WordPress" site:{site_domain}',
        f'intitle:"Just another WordPress site" site:{site_domain}'
    ]

    found_urls = set()
    base_url = "https://www.googleapis.com/customsearch/v1"

    for dork in dorks:
        logging.info(f"🔍 Mencari dengan dork: {dork!r}")
        start_index = 1
        fetched_for_this_dork = 0

        while fetched_for_this_dork < per_dork_limit:
            batch_size = min(10, per_dork_limit - fetched_for_this_dork)
            params = {
                "key": API_KEY,
                "cx": CX_ID,
                "q": dork,
                "start": start_index,
                "num": batch_size
            }
            try:
                resp = requests.get(base_url, params=params, timeout=10)
                data = resp.json().get("items", [])
            except Exception as e:
                logging.warning(f"  Gagal panggil CSE API (dork `{dork}`, start={start_index}): {e}")
                break

            if not data:
                break  # Tidak ada hasil lagi untuk dork ini

            for item in data:
                link = item.get("link", "")
                m = re.match(r"https?://[^/]+", link)
                if m:
                    found_urls.add(m.group(0))

            fetched_for_this_dork += len(data)
            start_index += len(data)

            if len(found_urls) >= total_limit:
                break

            time.sleep(delay_between)

        if len(found_urls) >= total_limit:
            break

        time.sleep(delay_between)

    result_list = list(found_urls)[:total_limit]
    logging.info(f"✅ Total URL unik yang terkumpul: {len(result_list)} (limit={total_limit})")
    return result_list

# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi utama (main)
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="WPscraper — Scrape konten WordPress via Google CSE API (multi‐dork)"
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Top-level domain atau sub-domain (contoh: or.id atau example.com)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Jumlah maksimum total situs unik WordPress yang ingin diambil (default: 200)."
    )
    parser.add_argument(
        "--per-dork",
        type=int,
        default=25,
        help="Maksimum hasil unik per dork Google (default: 25)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Jeda (detik) antara setiap panggilan ke CSE API (default: 1.0)."
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

    # 1) Baca daftar domain yang sudah tercatat
    scanned = read_scanned()
    logging.info(f"💾 Sudah pernah discrap: {len(scanned)} domain")

    # 2) Agar hasil akhir berjumlah `total_limit` domain baru, tarik `limit + scanned_count`
    cse_fetch_limit = total_limit + len(scanned)
    logging.info(f"🚀 Mulai mengumpulkan target (limit+scanned={cse_fetch_limit})")
    all_targets = get_wp_targets_cse(domain, cse_fetch_limit, per_dork_limit, delay_between)

    # 3) Filter supaya hanya domain baru (belum pernah di‐scrap), lalu batasi ke `total_limit`
    new_targets = [t for t in all_targets if t not in scanned][:total_limit]
    if not new_targets:
        logging.info("🔄 Tidak ada target baru yang belum pernah discrap. Proses dihentikan.")
        sys.exit(0)

    logging.info(f"✨ Ditemukan {len(new_targets)} target baru yang akan discrap.")

    # 4) Buka file output (mode append)
    try:
        outf = open(output_file, "a", encoding="utf-8")
    except Exception as e:
        logging.error(f"Gagal membuka file `{output_file}` untuk ditulis: {e}")
        sys.exit(1)

    # 5) Iterasi tiap target baru, ambil teks, tulis, dan catat sebagai 'scanned'
    for idx, site_url in enumerate(new_targets, start=1):
        logging.info(f"[{idx}/{len(new_targets)}] Fetch & ekstrak teks: {site_url}")
        page_text = fetch_and_extract_text(site_url, timeout=timeout_fetch)
        if page_text:
            outf.write(f"--- URL: {site_url}\n")
            outf.write(page_text + "\n\n")
            outf.write(("=" * 80) + "\n\n")
        else:
            logging.warning(f"   (⚠️) Gagal mengekstrak teks dari: {site_url}")

        # Simpan domain ke file scanned
        append_scanned(site_url)
        # Jeda sebelum request berikutnya
        time.sleep(delay_between)

    outf.close()
    logging.info(f"✅ Proses selesai. Semua hasil ditambahkan di `{output_file}` dan domain tercatat di `{SCANNED_FILE}`.")


if __name__ == "__main__":
    main()
