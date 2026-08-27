"""Bulk-download orchestration across many listed companies at once.

Meant for "grab every company's reports" runs that can span hours and get
interrupted (a crash, a rate limit, Ctrl-C, the laptop going to sleep) -
run_all() writes a JSON checkpoint after every single company so a re-run
with resume=True picks up from the first company not yet marked "done"
instead of starting over from the beginning.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Iterable

from . import downloader

logger = logging.getLogger("idx_report_scraper")

CHECKPOINT_FILENAME = "progress.json"
DEFAULT_DELAY_SECONDS = 1.0


def _maybe_add_ticker(seen: dict, cell: str) -> None:
    cell = (cell or "").strip()
    if not cell or cell.startswith("#"):
        return
    code = cell.upper()
    if 1 < len(code) <= 5 and code.isalpha():
        seen.setdefault(code, None)


def load_tickers_from_file(path: Path) -> list[str]:
    """Read ticker codes from a plain-text or CSV file: one per line, or a
    column of a CSV (its header, if any, is matched by name against
    "kode"/"code"/"ticker", falling back to the first column). Blank lines
    and '#'-comments are ignored; duplicates are dropped while keeping
    first-seen order.
    """
    path = Path(path)
    seen: dict[str, None] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        if path.suffix.lower() == ".csv":
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            code_field = next(
                (name for name in fieldnames if any(k in name.lower() for k in ("kode", "code", "ticker"))),
                fieldnames[0] if fieldnames else None,
            )
            if code_field is not None:
                for row in reader:
                    _maybe_add_ticker(seen, row.get(code_field, ""))
        else:
            for line in f:
                _maybe_add_ticker(seen, line)
    return list(seen)


def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_checkpoint(path: Path, checkpoint: dict) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def run_all(
    kode_emiten_list: Iterable[str],
    year: int,
    periods: Iterable[str] = downloader.DEFAULT_PERIODS,
    out_dir: Path = Path("downloads"),
    resume: bool = True,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> dict:
    """Run downloader.run() for every ticker, recording each one's outcome
    in <out_dir>/progress.json immediately after it finishes.

    With resume=True (the default), a ticker already marked "done" in an
    existing checkpoint is skipped - so re-running this after an
    interruption continues from the first ticker not yet done, rather than
    re-downloading everything. A ticker marked "failed" is retried.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_dir / CHECKPOINT_FILENAME
    checkpoint = _load_checkpoint(checkpoint_path) if resume else {}

    codes = list(dict.fromkeys(kode_emiten_list))
    total = len(codes)
    done_count = sum(1 for c in codes if checkpoint.get(c, {}).get("status") == "done")

    session = downloader.requests.Session(impersonate="chrome")
    try:
        for i, kode in enumerate(codes, start=1):
            if resume and checkpoint.get(kode, {}).get("status") == "done":
                logger.info("[%d/%d] %s sudah selesai sebelumnya, dilewati.", i, total, kode)
                continue

            logger.info("[%d/%d] Memproses %s ...", i, total, kode)
            try:
                results = downloader.run(
                    kode_emiten=kode, year=year, periods=periods, out_dir=out_dir, session=session
                )
                checkpoint[kode] = {"status": "done", "files": len(results)}
                done_count += 1
            except Exception as exc:
                logger.error("Gagal memproses %s: %s", kode, exc)
                checkpoint[kode] = {"status": "failed", "error": str(exc)}
            finally:
                _save_checkpoint(checkpoint_path, checkpoint)

            if delay_seconds and i < total:
                time.sleep(delay_seconds)
    finally:
        session.close()

    logger.info(
        "Selesai: %d/%d perusahaan sukses, checkpoint di %s", done_count, total, checkpoint_path
    )
    return checkpoint
