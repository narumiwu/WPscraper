#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import sys
import os
import argparse
import logging
import requests
from pathlib import Path
from typing import Set

# ──────────────────────────────────────────────────────────────────────────────
#   Google Custom Search API Credentials
#   (API pertama dan API kedua untuk fallback kuota)
# ──────────────────────────────────────────────────────────────────────────────
API_KEY_1 = "AIzaSyCUaVp0gWKw1B5FmFiplAXl-gkwQEr_rVg"
CX_ID_1   = "c680430dddc144471"

# *API kedua (jika API pertama kehabisan kuota, langsung ganti ke sini)*
API_KEY_2 = "AIzaSyCUaVp0gN7eIlqmwQOKwonDyTdl6-5I"
CX_ID_2   = "5454d756488a94e30"

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
    logging.warning(
        "Modul googlesearch-python tidak terinstall. "
        "Jika CSE API gagal, dork akan di-skip."
    )

# ──────────────────────────────────────────────────────────────────────────────
#  Fungsi: baca daftar domain yang sudah disimpan
# ──────────────────────────────────────────────────────────────────────────────
def read_scanned() -> Set[str]:
    if SCANNED_FILE.exists():
        return {
            line.strip()
            for line in SCANNED_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
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
#    Otomatis beralih ke API kedua jika API pertama gagal. Menggunakan proxy
#    jika --proxy di-pasangkan.
# ──────────────────────────────────────────────────────────────────────────────
def get_wp_targets_cse(
    site_domain: str,
    total_limit: int,
    per_dork_limit: int,
    delay_between: float,
    proxy: str = None
) -> list:
    """
    Mengumpulkan root domain situs WordPress di `site_domain` menggunakan beberapa dork
    melalui Google Custom Search JSON API, hingga mencapai `total_limit`. Jika API pertama
    gagal (status != 200 atau JSON tidak memuat 'items'), langsung gunakan API kedua.
    Jika API kedua juga gagal, barulah fallback ke googlesearch.search() (menggunakan proxy
    juga jika tersedia).
    """
    # Daftar dork (format "inurl:… site:…" sudah benar)
    dorks = [
        f'inurl:wp-content site:{site_domain}',
        f'inurl:wp-login.php site:{site_domain}',
        f'inurl:"/wp-content/plugins/wp-shopping-cart/" site:{site_domain}',
        f'inurl:"/wp-content/plugins/wp-dbmanager/" site:{site_domain}',
        f'inurl:"/wp-content/themes/" site:{site_domain}',
        f'inurl:readme.html site:{site_domain}',
        f'"Powered by WordPress" site:{site_domain}',
        f'intitle:"Just another WordPress site" site:{site_domain}',
    ]

    found_urls = set()
    base_url = "https://www.googleapis.com/customsearch/v1"

    # Siapkan dictionary proxies jika proxy di-pasangkan
    proxies = {"http": proxy, "https": proxy} if proxy else None

    # Kita mulai tiap dork
    for dork in dorks:
        logging.info(f"🔍 Mencari dengan dork (CSE): {dork!r}")
        start_index = 1
        fetched_for_this_dork = 0
        cse_found_this_dork = 0

        # Variabel lokal untuk menyimpan API key/CX yang sedang dipakai:
        key = API_KEY_1
        cx = CX_ID_1
        using_api = 1  # 1 berarti pakai API pertama; 2 berarti pakai API kedua

        # Tarik via CSE API hingga per_dork_limit, tapi pakai batch 10
        while fetched_for_this_dork < per_dork_limit:
            batch_size = min(10, per_dork_limit - fetched_for_this_dork)
            params = {
                "key": key,
                "cx": cx,
                "q": dork,
                "start": start_index,
                "num": batch_size
            }

            data = []
            try:
                resp = requests.get(base_url, params=params, timeout=10, proxies=proxies)
                if resp.status_code == 200:
                    data = resp.json().get("items", [])
                else:
                    # Jika API pertama (using_api==1) gagal, langsung coba API kedua
                    if using_api == 1:
                        logging.warning(
                            f"  ⚠️ API#1 gagal (dork `{dork}`, status={resp.status_code}). "
                            "Beralih ke API kedua…"
                        )
                        key = API_KEY_2
                        cx = CX_ID_2
                        using_api = 2
                        time.sleep(1)
                        continue
                    else:
                        # API kedua juga gagal, hentikan loop dan ke fallback
                        logging.warning(
                            f"  ⚠️ API#2 gagal (dork `{dork}`, status={resp.status_code}). "
                            "Siap fallback ke googlesearch."
                        )
                        data = []
                # End if resp.status_code
            except Exception as e:
                # Kondisi “request exception” juga memicu pindah API key jika masih di API pertama
                if using_api == 1:
                    logging.warning(
                        f"  ❌ API#1 exception (dork `{dork}`, idx={start_index}): {e}. "
                        "Beralih ke API kedua…"
                    )
                    key = API_KEY_2
                    cx = CX_ID_2
                    using_api = 2
                    time.sleep(1)
                    continue
                else:
                    logging.warning(
                        f"  ❌ API#2 exception (dork `{dork}`, idx={start_index}): {e}. "
                        "Siap fallback ke googlesearch."
                    )
                    data = []
            # End try / except

            # Setelah mencoba kedua API, jika data kosong => hentikan loop CSE
            if not data:
                break

            # Proses data yg berhasil dipanggil (items)
            for item in data:
                link = item.get("link", "")
                m = re.match(r"https?://[^/]+", link)
                if m:
                    found_urls.add(m.group(0))

            num_got = len(data)
            fetched_for_this_dork += num_got
            cse_found_this_dork += num_got
            start_index += num_got

            # Jika sudah cukup mencapai total_limit, hentikan semuanya
            if len(found_urls) >= total_limit:
                break

            time.sleep(delay_between)

        # << Tambahan kecil: Jika setelah loop CSE, cse_found_this_dork masih 0,
        #    langsung skip dork ini (tanpa fallback googlesearch) jika user tidak ingin fallback. >>
        # (Namun jika ingin fallback, baris ini bisa di-comment dan tetap gunakan blok di bawah.)
        # if cse_found_this_dork == 0:
        #     logging.warning(
        #         f"⚠️ CSE API (API#1/API#2) tidak ada hasil untuk '{dork}'. Lewati dork ini."
        #     )
        #     break

        # Jika CSE API **benar‐benar** tidak mengembalikan satupun (cse_found_this_dork == 0),
        # dan modul googlesearch‐python terinstall, barulah pakai fallback:
        if cse_found_this_dork == 0 and FALLBACK_GOOGLESEARCH:
            logging.info(
                f"   ⚠️ CSE API (baik API#1 maupun API#2) tidak ada hasil untuk `{dork}`. "
                "Fallback pakai googlesearch."
            )
            fallback_count = 0

            # Jika proxy di-pasangkan, set environment bagi googlesearch
            if proxy:
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy

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

        # Jika sudah mencapai total_limit, keluar kedalam loop
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
        description="WPscraper — Hanya fetch root‐link WordPress via Google CSE API (dua API keys) + fallback"
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
        default=2.0,
        help="Jeda (detik) antara setiap panggilan ke CSE API / fallback (default: 2.0)."
    )
    parser.add_argument(
        "--proxy",
        help="Proxy (misal: http://user:pass@host:port atau socks5://host:port)."
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
    proxy = args.proxy
    output_file = args.output

    # 1) Baca daftar domain yang sudah tercatat
    scanned = read_scanned()
    logging.info(f"💾 Sudah pernah discrap: {len(scanned)} domain")

    # 2) Tarik `total_limit + scanned_count` agar nanti tetap dapat `total_limit` domain baru
    cse_fetch_limit = total_limit + len(scanned)
    logging.info(f"🚀 Mulai mengumpulkan tautan (limit+scanned={cse_fetch_limit})")
    all_targets = get_wp_targets_cse(domain, cse_fetch_limit, per_dork_limit, delay_between, proxy)

    # 3) Filter hanya domain baru (belum pernah discrap), lalu batasi ke `total_limit`
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
    logging.info(
        f"✅ Selesai. Semua link domain disimpan di `{output_file}` dan domain tercatat di `{SCANNED_FILE}`."
    )

if __name__ == "__main__":
    main()
