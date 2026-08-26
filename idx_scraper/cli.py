"""Command-line entry point: fetch and download IDX financial-report PDFs.

Examples:
    # One company, one year, every period.
    python -m idx_scraper.cli --kode-emiten AADI --year 2026

    # Every listed company, one year, dry-run preview only.
    python -m idx_scraper.cli --kode-emiten all --year 2026 --dry-run

    # A handful of companies, a year range, only Q2.
    python -m idx_scraper.cli --kode-emiten AADI ADRO --year 2020-2026 --periode tw2

    # Everything IDX has, for every company, from each company's own
    # listing year through the current year. Heavy -- see README.
    python -m idx_scraper.cli --kode-emiten all --year all --max-workers 4
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from idx_scraper.client import IDXClient
from idx_scraper.companies import Company, list_companies
from idx_scraper.config import COMPANY_TICKERS, DEFAULT_REPORT_TYPE, FALLBACK_MIN_YEAR, PERIODS
from idx_scraper.downloader import download_report
from idx_scraper.session import create_session

logger = logging.getLogger("idx_scraper")

_manifest_lock = threading.Lock()


def resolve_ticker(value: str) -> str:
    key = value.strip().lower()
    return COMPANY_TICKERS.get(key, value.strip().upper())


def parse_year_tokens(tokens: list[str], listing_year: int | None, current_year: int) -> list[int]:
    """Expand CLI year tokens ("2026", "2020-2026", "all") into a sorted
    list of concrete years. "all" spans from the company's own listing
    year (when known) through the current year."""
    years: set[int] = set()
    for token in tokens:
        token = token.strip().lower()
        if token == "all":
            start = listing_year or FALLBACK_MIN_YEAR
            years.update(range(start, current_year + 1))
        elif "-" in token:
            start_s, end_s = token.split("-", 1)
            start, end = int(start_s), int(end_s)
            years.update(range(min(start, end), max(start, end) + 1))
        else:
            years.add(int(token))
    return sorted(years)


def resolve_companies(args, session) -> list[Company]:
    tokens = [t.strip() for t in args.kode_emiten]
    if any(t.lower() == "all" for t in tokens):
        companies = list_companies(session, sector=args.sector, board=args.board)
        if args.limit:
            companies = companies[: args.limit]
        return companies
    return [Company(code=resolve_ticker(t), name=t) for t in tokens]


class ManifestWriter:
    """Append-only CSV log of what was found/downloaded, so a large,
    multi-company run stays auditable and resumable without re-reading
    every log line."""

    _FIELDS = (
        "timestamp",
        "kode_emiten",
        "year",
        "periode",
        "files_found",
        "files_downloaded",
        "note",
    )

    def __init__(self, path: Path | None):
        self.path = path
        if self.path:
            is_new = not self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fh, fieldnames=self._FIELDS)
            if is_new:
                self._writer.writeheader()
                self._fh.flush()

    def record(self, **row) -> None:
        if not self.path:
            return
        row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        with _manifest_lock:
            self._writer.writerow(row)
            self._fh.flush()

    def close(self) -> None:
        if self.path:
            self._fh.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--kode-emiten",
        required=True,
        nargs="+",
        help=(
            "One or more ticker codes (e.g. AADI ADRO), known company names, "
            "or the literal 'all' to cover every company listed on IDX."
        ),
    )
    parser.add_argument(
        "--year",
        required=True,
        nargs="+",
        help=(
            "Fiscal year(s). Accepts single years (2026), ranges "
            "(2020-2026), or 'all' (each company's listing year through "
            "the current year). Multiple tokens are unioned."
        ),
    )
    parser.add_argument(
        "--periode",
        choices=(*PERIODS, "all"),
        default="all",
        help="Reporting period. 'all' tries every period known to the API (default).",
    )
    parser.add_argument("--report-type", default=DEFAULT_REPORT_TYPE)
    parser.add_argument(
        "--sector", default="", help="Filter 'all' companies by IDX sector (server-side)."
    )
    parser.add_argument(
        "--board", default="", help="Filter 'all' companies by listing board (server-side)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of companies processed -- handy for a smoke test before a full run.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Root folder PDFs are organized under (default: ./data).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="CSV log of what was found/downloaded per company/year/period "
        "(default: <output-dir>/manifest.csv).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded without saving any file.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Re-download existing files.")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Companies processed concurrently (default: 1, sequential). "
        "Raise cautiously -- IDX is not documented to tolerate heavy parallel load.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.3,
        help="Seconds to wait before each year/period listing request (politeness delay).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def process_company(
    company: Company,
    args,
    client: IDXClient,
    current_year: int,
    manifest: ManifestWriter,
) -> tuple[int, int]:
    """Fetch + (optionally) download every requested year/period for one
    company. Returns (files_found, files_downloaded)."""
    years = parse_year_tokens(args.year, company.listing_year, current_year)
    periods = PERIODS if args.periode == "all" else (args.periode,)
    found = 0
    saved = 0

    for year in years:
        for periode in periods:
            time.sleep(args.request_delay)
            try:
                reports = client.fetch_report_files(
                    kode_emiten=company.code,
                    year=year,
                    periode=periode,
                    report_type=args.report_type,
                )
            except RuntimeError as exc:
                logger.error("Could not fetch %s %s %s: %s", company.code, year, periode, exc)
                manifest.record(
                    kode_emiten=company.code, year=year, periode=periode,
                    files_found=0, files_downloaded=0, note=f"error: {exc}",
                )
                continue

            if not reports:
                manifest.record(
                    kode_emiten=company.code, year=year, periode=periode,
                    files_found=0, files_downloaded=0, note="not published",
                )
                continue

            found += len(reports)
            downloaded_here = 0
            for report in reports:
                if args.dry_run:
                    logger.info("[dry-run] would download: %s", report.download_url)
                    continue
                saved_path = download_report(
                    report, args.output_dir, client.session, overwrite=args.overwrite
                )
                if saved_path:
                    saved += 1
                    downloaded_here += 1

            manifest.record(
                kode_emiten=company.code, year=year, periode=periode,
                files_found=len(reports), files_downloaded=downloaded_here,
                note="dry-run" if args.dry_run else "",
            )

    return found, saved


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    session = create_session()
    companies = resolve_companies(args, session)
    if not companies:
        logger.error("No companies resolved from --kode-emiten %r.", args.kode_emiten)
        return 1

    logger.info("Processing %d compan%s.", len(companies), "y" if len(companies) == 1 else "ies")

    client = IDXClient(session=session)
    current_year = datetime.now().year
    manifest = ManifestWriter(args.manifest or (args.output_dir / "manifest.csv"))

    total_found = 0
    total_saved = 0

    try:
        if args.max_workers <= 1:
            for i, company in enumerate(companies, start=1):
                logger.info("[%d/%d] %s (%s)", i, len(companies), company.code, company.name)
                found, saved = process_company(company, args, client, current_year, manifest)
                total_found += found
                total_saved += saved
        else:
            with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
                futures = {
                    pool.submit(
                        process_company, company, args, client, current_year, manifest
                    ): company
                    for company in companies
                }
                for i, future in enumerate(as_completed(futures), start=1):
                    company = futures[future]
                    try:
                        found, saved = future.result()
                    except Exception:
                        logger.exception("Unhandled error processing %s", company.code)
                        continue
                    total_found += found
                    total_saved += saved
                    logger.info("[%d/%d done] %s", i, len(companies), company.code)
    finally:
        manifest.close()

    logger.info(
        "Done. %d PDF(s) found, %d downloaded (dry_run=%s) under %s. Manifest: %s",
        total_found,
        total_saved,
        args.dry_run,
        args.output_dir,
        args.manifest or (args.output_dir / "manifest.csv"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
