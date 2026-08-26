"""Command-line entry point: fetch and download IDX financial-report PDFs.

Example:
    python -m idx_scraper.cli --kode-emiten AADI --year 2026
    python -m idx_scraper.cli --kode-emiten AADI --year 2026 --periode tw2 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from idx_scraper.client import IDXClient
from idx_scraper.config import COMPANY_TICKERS, DEFAULT_REPORT_TYPE, PERIODS
from idx_scraper.downloader import download_report

logger = logging.getLogger("idx_scraper")


def resolve_ticker(value: str) -> str:
    key = value.strip().lower()
    return COMPANY_TICKERS.get(key, value.strip().upper())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kode-emiten",
        required=True,
        help="Ticker code (e.g. AADI) or a known company name (e.g. 'Adaro Andalan Indonesia').",
    )
    parser.add_argument("--year", required=True, type=int, help="Fiscal year, e.g. 2026.")
    parser.add_argument(
        "--periode",
        choices=(*PERIODS, "all"),
        default="all",
        help="Reporting period. 'all' tries every period known to the API (default).",
    )
    parser.add_argument("--report-type", default=DEFAULT_REPORT_TYPE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Root folder PDFs are organized under (default: ./data).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded without saving any file.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Re-download existing files.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    kode_emiten = resolve_ticker(args.kode_emiten)
    periods = PERIODS if args.periode == "all" else (args.periode,)

    client = IDXClient()
    total_found = 0
    total_saved = 0

    for periode in periods:
        try:
            reports = client.fetch_report_files(
                kode_emiten=kode_emiten,
                year=args.year,
                periode=periode,
                report_type=args.report_type,
            )
        except RuntimeError as exc:
            logger.error("Could not fetch %s %s: %s", kode_emiten, periode, exc)
            continue

        if not reports:
            logger.info("No %s report published yet for %s %s.", periode, kode_emiten, args.year)
            continue

        total_found += len(reports)
        for report in reports:
            if args.dry_run:
                logger.info("[dry-run] would download: %s", report.download_url)
                continue
            saved = download_report(
                report, args.output_dir, client.session, overwrite=args.overwrite
            )
            if saved:
                total_saved += 1

    logger.info(
        "Done. %d PDF(s) found, %d downloaded (dry_run=%s) under %s",
        total_found,
        total_saved,
        args.dry_run,
        args.output_dir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
