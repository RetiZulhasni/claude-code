"""Extract issuer identity (entity name/code) from a financial-report PDF.

IDX's report cover page carries these as a labeled row - in a table on most
reports, but as plain text on some - in Indonesian ("Nama Entitas"/"Kode
Entitas") or English ("Entity Name"/"Entity Code"). Trying the table first
and only falling back to a text scan is what makes this work across the
different PDF templates IDX has used over the years, while staying cheap
for the common case (a handful of pages, not the whole document).
"""

from __future__ import annotations

import re

import pdfplumber

_NORMALIZE_WHITESPACE = re.compile(r"\s+")
_LABELS_COMPANY = {"nama entitas", "entity name"}
_LABELS_CODE = {"kode entitas", "entity code"}
_MAX_TABLE_PAGES = 2
_MAX_TEXT_PAGES = 3


def _cell_text(value) -> str:
    return _NORMALIZE_WHITESPACE.sub(" ", str(value or "")).strip()


def _from_tables(pdf) -> tuple[str | None, str | None]:
    company = code = None
    for page in pdf.pages[:_MAX_TABLE_PAGES]:
        for table in page.extract_tables() or []:
            for row in table or []:
                for i, cell in enumerate(row or []):
                    label = _cell_text(cell).lower()
                    if label in _LABELS_COMPANY and i + 1 < len(row):
                        company = company or _cell_text(row[i + 1])
                    if label in _LABELS_CODE and i + 1 < len(row):
                        code = code or _cell_text(row[i + 1])
        if company and code:
            break
    return company, code


def _pick_after(text: str, *patterns: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern + r"\s*[:\-]?\s*(.+)", text, re.I)
        if match:
            return _cell_text(match.group(1).splitlines()[0])
    return None


def _from_text(pdf) -> tuple[str | None, str | None]:
    text = "\n".join((p.extract_text() or "") for p in pdf.pages[:_MAX_TEXT_PAGES])
    company = _pick_after(text, r"nama\s+entitas", r"entity\s+name")
    code = _pick_after(text, r"kode\s+entitas", r"entity\s+code")
    return company, code


def extract_entity_metadata(pdf_source) -> tuple[str | None, str | None]:
    """Return (entity_name, entity_code) read off a report's cover page.

    pdf_source is anything pdfplumber.open() accepts (a path or a
    file-like object). Returns (None, None) rather than raising when
    neither label is found, since not every report template exposes them.
    """
    with pdfplumber.open(pdf_source) as pdf:
        company, code = _from_tables(pdf)
        if not (company and code):
            text_company, text_code = _from_text(pdf)
            company = company or text_company
            code = code or text_code
    return company, code
