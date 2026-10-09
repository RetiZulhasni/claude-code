"""Check how well financials.py generalizes beyond AALI, using PDFs already
downloaded (e.g. via --tickers-file sample_tickers.txt).

For every ticker it reports which FinancialProfile fields came out empty and
runs internal consistency checks that need no external reference data:

- balance sheet identity: total assets == total liabilities + total equity
- current assets <= total assets, current liabilities <= total liabilities
- gross profit == revenue - cost of revenue (when all three are present)

A field that is None, or a check that fails, points at a label the parser
doesn't recognize for that company's template (typically banks/insurers,
whose OJK XBRL layout differs from the general-industry one).

    python -m idx_report_scraper.validation --year 2025 --output validasi.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from dataclasses import asdict, fields
from pathlib import Path

from . import financials, intelligence

logger = logging.getLogger("idx_report_scraper")

NUMERIC_FIELDS = [
    f.name for f in fields(financials.FinancialProfile)
    if f.name not in ("entity_name", "entity_code", "sektor", "subsektor", "industri", "jenis_laporan")
]
TEXT_FIELDS = ["entity_name", "sektor", "subsektor", "industri", "jenis_laporan"]

# Relative tolerance for identities; reports round to the unit presented, so
# allow a hair of slack rather than demanding exact equality.
TOLERANCE = 0.005


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b), 1.0)


def check_profile(p: financials.FinancialProfile) -> dict[str, str]:
    """Return {check_name: "OK" | "GAGAL" | "N/A"} for one profile."""
    results = {}

    if None in (p.jumlah_aset, p.jumlah_liabilitas, p.jumlah_ekuitas):
        results["aset=liab+ekuitas"] = "N/A"
    else:
        results["aset=liab+ekuitas"] = (
            "OK" if _close(p.jumlah_aset, p.jumlah_liabilitas + p.jumlah_ekuitas) else "GAGAL"
        )

    if None in (p.jumlah_aset_lancar, p.jumlah_aset):
        results["aset_lancar<=aset"] = "N/A"
    else:
        results["aset_lancar<=aset"] = "OK" if p.jumlah_aset_lancar <= p.jumlah_aset else "GAGAL"

    if None in (p.jumlah_liabilitas_jangka_pendek, p.jumlah_liabilitas):
        results["liab_jp<=liab"] = "N/A"
    else:
        results["liab_jp<=liab"] = (
            "OK" if p.jumlah_liabilitas_jangka_pendek <= p.jumlah_liabilitas else "GAGAL"
        )

    if None in (p.pendapatan, p.beban_pokok_penjualan, p.laba_bruto):
        results["laba_bruto=pendapatan-bpp"] = "N/A"
    else:
        # Cost of revenue is shown negative (in parentheses) in IDX reports.
        results["laba_bruto=pendapatan-bpp"] = (
            "OK" if _close(p.laba_bruto, p.pendapatan - abs(p.beban_pokok_penjualan)) else "GAGAL"
        )

    return results


def validate(out_dir: Path, year: int, tickers: list[str]) -> list[dict]:
    rows = []
    for kode, periode, profile in intelligence.collect_financial_profiles(out_dir, year, tickers):
        data = asdict(profile)
        missing = [name for name in NUMERIC_FIELDS + TEXT_FIELDS if data[name] in (None, "")]
        row = {"kode": kode, "periode": periode, **data}
        row.update(check_profile(profile))
        row["field_kosong"] = ", ".join(missing)
        row["jumlah_field_kosong"] = len(missing)
        rows.append(row)
    return rows


def summarize(rows: list[dict], tickers: list[str]) -> str:
    lines = []
    parsed = {r["kode"] for r in rows}
    not_parsed = [t for t in tickers if t not in parsed]
    lines.append(f"Emiten diminta: {len(tickers)}, berhasil diekstrak: {len(rows)}")
    if not_parsed:
        lines.append(f"Tanpa PDF / gagal parse: {', '.join(not_parsed)}")

    lines.append("\nCakupan field (terisi / total):")
    for name in TEXT_FIELDS + NUMERIC_FIELDS:
        filled = sum(1 for r in rows if r[name] not in (None, ""))
        lines.append(f"  {name:<34} {filled:>3}/{len(rows)}")

    lines.append("\nPemeriksaan konsistensi (OK / GAGAL / N/A):")
    for check in ("aset=liab+ekuitas", "aset_lancar<=aset", "liab_jp<=liab", "laba_bruto=pendapatan-bpp"):
        counts = defaultdict(int)
        for r in rows:
            counts[r[check]] += 1
        lines.append(f"  {check:<34} {counts['OK']:>3} / {counts['GAGAL']:>3} / {counts['N/A']:>3}")

    lines.append("\nRata-rata field kosong per sektor:")
    by_sector = defaultdict(list)
    for r in rows:
        by_sector[r["sektor"] or "(sektor tidak terbaca)"].append(r["jumlah_field_kosong"])
    for sektor, counts in sorted(by_sector.items()):
        lines.append(f"  {sektor:<40} {sum(counts) / len(counts):5.1f}  (n={len(counts)})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from .bulk import load_tickers_from_file

    parser = argparse.ArgumentParser(description="Validasi ekstraksi financials.py pada PDF terunduh")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("downloads"))
    parser.add_argument(
        "--tickers-file", type=Path,
        help="Default: semua emiten yang sudah punya manifest di --out-dir/<year>",
    )
    parser.add_argument("--output", type=Path, default=Path("validasi_ekstraksi.csv"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.tickers_file:
        tickers = load_tickers_from_file(args.tickers_file)
    else:
        tickers = intelligence.discover_downloaded_tickers(args.out_dir, args.year)

    rows = validate(args.out_dir, args.year, tickers)
    if rows:
        with args.output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Detail per emiten ditulis ke %s", args.output)
    print(summarize(rows, tickers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
