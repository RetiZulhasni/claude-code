"""Saves ReportFile PDFs to a structured on-disk layout."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests

from idx_scraper.client import ReportFile

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    name = name.rsplit("/", 1)[-1]
    return _SAFE_NAME_RE.sub("_", name) or "report.pdf"


def destination_for(report: ReportFile, output_dir: Path) -> Path:
    """data/<KODE_EMITEN>/<YEAR>/<PERIODE>/<file_name>.pdf"""
    return (
        output_dir
        / report.kode_emiten.upper()
        / report.year
        / report.periode
        / _safe_filename(report.file_name)
    )


def download_report(
    report: ReportFile,
    output_dir: Path,
    session: requests.Session,
    *,
    timeout: float = 60.0,
    overwrite: bool = False,
    polite_delay: float = 0.5,
) -> Path | None:
    """Download one PDF, skipping it if already present. Returns the path
    written, or None if the file already existed and was skipped."""
    target = destination_for(report, output_dir)

    if target.exists() and not overwrite:
        logger.info("Skipping (already exists): %s", target)
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".part")

    logger.info("Downloading %s -> %s", report.download_url, target)
    with session.get(report.download_url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(tmp_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)

    tmp_path.replace(target)
    if polite_delay:
        time.sleep(polite_delay)
    return target
