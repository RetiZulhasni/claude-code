"""CLI entrypoint: python -m idx_report_scraper.cli --company "..." --year 2026"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from curl_cffi import requests

from . import companies, downloader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unduh laporan keuangan (PDF) emiten IDX secara otomatis.",
    )
    company_group = parser.add_mutually_exclusive_group(required=True)
    company_group.add_argument(
        "--company",
        help='Nama perusahaan, mis. "PT Adaro Andalan Indonesia Tbk" (harus dikenal di companies.py)',
    )
    company_group.add_argument(
        "--kode-emiten",
        help="Kode ticker IDX secara langsung, mis. AADI",
    )
    parser.add_argument("--year", type=int, required=True, help="Tahun laporan, mis. 2026")
    parser.add_argument(
        "--periode",
        nargs="+",
        choices=downloader.VALID_PERIODS,
        default=list(downloader.DEFAULT_PERIODS),
        help="Periode laporan yang diambil (default: semua periode)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("downloads"),
        help="Folder tujuan unduhan (default: ./downloads)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    log = logging.getLogger("idx_report_scraper")

    try:
        kode_emiten = args.kode_emiten or companies.resolve(args.company)
    except ValueError as exc:
        log.error(str(exc))
        return 2

    try:
        results = downloader.run(
            kode_emiten=kode_emiten,
            year=args.year,
            periods=args.periode,
            out_dir=args.out_dir,
        )
    except requests.exceptions.RequestException as exc:
        log.error("Gagal menghubungi idx.co.id: %s", exc)
        return 3

    if not results:
        log.warning(
            "Tidak ada PDF yang berhasil diunduh untuk %s tahun %s.", kode_emiten, args.year
        )
        return 1

    print(f"Berhasil mengunduh {len(results)} file PDF untuk {kode_emiten} tahun {args.year}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
