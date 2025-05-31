#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import sys
import argparse
import logging
import requests                    # <― Pastikan modul requests di‐import
from pathlib import Path
from typing import Set

# ──────────────────────────────────────────────────────────────────────────────
#   Google Custom Search API Credentials (ganti dengan milik Anda)
# ──────────────────────────────────────────────────────────────────────────────
API_KEY = "AIzaSyCUaVp0gWKw1B5FmFiplAXl-gkwQEr_rVg"
CX_ID   = "c680430dddc144471"

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
#  Cobalah import modul googlesearch; jika tidak ada, fallback=False
# ──────────────────────────────────────────────────────────────────────────────
try:
    from googlesearch import search
    FALLBACK_GOOGLESEARCH = True
except ImportError:
    FALLBACK_GOOGLESEARCH = False
    logging.warning("Modul googlesearch-python tidak terinstall. Jika CSE API gagal, dork akan di-skip.")

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
#  Fungsi: get_wp_targets_cse
#    Mengumpulkan root‐domain WordPress via Google CSE API (+ fallback).
# ──────────────────────────────────────────────────────────────────────────────
def get_wp_targets_cse(site_domain: str,
                       total_limit: int,
                       per_dork_limit: int,
                       delay_between: float) -> list:
    """
    Mengumpulkan root domain situs WordPress di `site_domain` menggunakan beberapa dork
    melalui Google Custom Search JSON API, hingga mencapai `total_limit`. Jika CSE API
    untuk suatu dork mengembalikan 0 hasil, fallback ke googlesearch.search() (jika tersedia).
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
        logging.info(f"🔍 Mencari dengan dork (CSE): {dork!r}")
        start_index = 1
        fetched_for_this_dork = 0
        cse_found_this_dork = 0

        # Tarik via CSE API dulu, maksimum per_dork_limit
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
                logging.warning(f"  ❌ CSE API gagal (dork `{dork}`, start={start_index}): {e}")
                data = []

            if not data:
                break  # tidak ada hasil via CSE

            for item in data:
                link = item.get("link", "")
                m = re.match(r"https?://[^/]+", link)
                if m:
                    found_urls.add(m.group(0))

            num_got = len(data)
            fetched_for_this_dork += num_got
            cse_found_this_dork += num_got
            start_index += num_got

            if len(found_urls) >= total_limit:
                break

            time.sleep(delay_between)

        # Jika CSE API mengembalikan 0 untuk dork ini, fallback ke googlesearch jika tersedia
        if cse_found_this_dork == 0 and FALLBACK_GOOGLESEARCH:
            logging.info(f"   ⚠️ CSE API tidak ada hasil untuk `{dork}`. Fallback pakai googlesearch.")
            fallback_count = 0
            try:
                for url in search(dork, num_results=per_dork_limit):
                    m = re.match(r"https?://[^/]+", url)
                    if m:
                        found_urls.add(m.group(0))
                    fallback_count += 1
                    if fallback_count >= per_dork_limit:
                        break
                    time.sleep(delay_between)
            except Exception as e:
                logging.warning(f"   ❌ Fallback googlesearch gagal (dork `{dork}`): {e}")

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
        description="WPscraper — Hanya fetch root‐link WordPress via Google CSE API (+ fallback)"
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
        help="Jumlah maksimum total domain WordPress yang ingin diambil (default: 200)."
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
        help="Jeda (detik) antara setiap panggilan ke CSE API / fallback (default: 1.0)."
    )
    parser.add_argument(
        "--output",
        default="wp_sites_links.txt",
        help="Nama file keluaran yang berisi pure link domain (default: wp_sites_links.txt)."
    )
    args = parser.parse_args()

    domain = args.domain
    total_limit = args.limit
    per_dork_limit = args.per_dork
    delay_between = args.delay
    output_file = args.output

    # 1) Baca daftar domain yang sudah tercatat
    scanned = read_scanned()
    logging.info(f"💾 Sudah pernah discrap: {len(scanned)} domain")

    # 2) Tarik `total_limit + scanned_count` agar nanti kita tetap mendapatkan `total_limit` domain baru
    cse_fetch_limit = total_limit + len(scanned)
    logging.info(f"🚀 Mulai mengumpulkan tautan (limit+scanned={cse_fetch_limit})")
    all_targets = get_wp_targets_cse(domain, cse_fetch_limit, per_dork_limit, delay_between)

    # 3) Filter hanya domain yang belum discrap, lalu batasi ke `total_limit`
    new_targets = [t for t in all_targets if t not in scanned][:total_limit]
    if not new_targets:
        logging.info("🔄 Tidak ada domain baru. Proses dihentikan.")
        sys.exit(0)

    logging.info(f"✨ Ditemukan {len(new_targets)} domain baru yang akan disimpan.")

    # 4) Buka file output (mode append)
    try:
        outf = open(output_file, "a", encoding="utf-8")
    except Exception as e:
        logging.error(f"Gagal membuka file `{output_file}` untuk ditulis: {e}")
        sys.exit(1)

    # 5) Tuliskan setiap domain baru ke file output, lalu catat di SCANNED_FILE
    for idx, site_url in enumerate(new_targets, start=1):
        logging.info(f"[{idx}/{len(new_targets)}] Menyimpan link: {site_url}")
        outf.write(site_url + "\n")
        append_scanned(site_url)
        time.sleep(delay_between)

    outf.close()
    logging.info(f"✅ Selesai. Semua link domain disimpan di `{output_file}` dan domain tercatat di `{SCANNED_FILE}`.")


if __name__ == "__main__":
    main()
