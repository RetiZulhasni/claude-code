"""Fetches the master list of tickers listed on IDX.

Backs the CLI's ``--kode-emiten all`` mode, so a run can cover every listed
company instead of one named ticker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from idx_scraper.config import SECURITIES_ENDPOINT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Company:
    code: str
    name: str
    listing_board: str | None = None
    listing_date: str | None = None

    @property
    def listing_year(self) -> int | None:
        """Best-effort year the company was first listed, parsed from
        whatever date format IDX happens to send (typically ISO-ish)."""
        if not self.listing_date:
            return None
        digits = "".join(ch for ch in self.listing_date[:4] if ch.isdigit())
        return int(digits) if len(digits) == 4 else None


def list_companies(
    session: requests.Session,
    *,
    sector: str = "",
    board: str = "",
    code: str = "",
    timeout: float = 20.0,
) -> list[Company]:
    """Return every listed company from IDX's securities master list,
    optionally filtered server-side by sector/board/code."""
    params = {"start": 0, "length": 9999, "code": code, "sector": sector, "board": board}
    response = session.get(SECURITIES_ENDPOINT, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    rows = (payload or {}).get("data") or []
    companies = [
        Company(
            code=row["Code"].strip().upper(),
            name=(row.get("Name") or "").strip(),
            listing_board=row.get("ListingBoard"),
            listing_date=row.get("ListingDate"),
        )
        for row in rows
        if row.get("Code")
    ]
    logger.info(
        "Fetched %d listed companies from IDX (sector=%r, board=%r).",
        len(companies),
        sector,
        board,
    )
    return companies
