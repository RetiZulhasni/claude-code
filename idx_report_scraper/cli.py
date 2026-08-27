"""CLI entrypoint: python -m idx_report_scraper.cli --company "..." --year 2026"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from curl_cffi import requests

from . import bulk, companies, downloader


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
    company_group.add_argument(
        "--tickers-file",
        type=Path,
        help=(
            "Proses banyak emiten sekaligus: file teks/CSV berisi satu kode ticker per baris "
            "(atau kolom pertama untuk CSV). Progres disimpan di <out-dir>/progress.json, "
            "sehingga run yang terhenti (crash, error, Ctrl-C) bisa dilanjutkan dari emiten "
            "yang belum selesai dengan menjalankan perintah yang sama lagi."
        ),
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
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Untuk --tickers-file: abaikan progress.json yang ada dan proses ulang semua emiten",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=bulk.DEFAULT_DELAY_SECONDS,
        help=(
            "Untuk --tickers-file: jeda (detik) antar-emiten agar tidak membebani idx.co.id "
            f"(default: {bulk.DEFAULT_DELAY_SECONDS})"
        ),
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help=(
            "Lewati endpoint API GetFinancialReport sepenuhnya dan langsung pakai pola URL PDF "
            "statis yang sudah diverifikasi (berguna kalau endpoint API sedang tidak stabil - "
            "404/403 - padahal URL file-nya sendiri terverifikasi benar)"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug")
    return parser


def _run_single(args, log: logging.Logger) -> int:
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
            use_api=not args.direct,
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


def _run_bulk(args, log: logging.Logger) -> int:
    tickers = bulk.load_tickers_from_file(args.tickers_file)
    if not tickers:
        log.error("Tidak ada kode ticker yang terbaca dari %s.", args.tickers_file)
        return 2

    checkpoint = bulk.run_all(
        tickers,
        year=args.year,
        periods=args.periode,
        out_dir=args.out_dir,
        resume=not args.no_resume,
        delay_seconds=args.delay,
        use_api=not args.direct,
    )

    failed = [k for k, v in checkpoint.items() if v.get("status") == "failed"]
    done = [k for k, v in checkpoint.items() if v.get("status") == "done"]
    print(f"Selesai: {len(done)}/{len(tickers)} emiten berhasil diproses untuk tahun {args.year}.")
    if failed:
        print(
            f"{len(failed)} emiten gagal: {', '.join(failed)}. "
            "Jalankan perintah yang sama lagi untuk melanjutkan/mencoba ulang."
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    log = logging.getLogger("idx_report_scraper")

    if args.tickers_file:
        return _run_bulk(args, log)
    return _run_single(args, log)


if __name__ == "__main__":
    sys.exit(main())
