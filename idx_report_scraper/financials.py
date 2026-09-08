"""Extract structured financial figures + basic profile fields from a
downloaded IDX financial-report PDF.

Unlike metadata.py (which only reads the entity name/code off the cover
page), this parses the XBRL-derived statement body itself: it locates each
statement's tagged section header (e.g. "[1210000] Statement of financial
position...") by its English half, then searches within that section for
specific line labels. IDX's PDF renderer keeps each labeled row - Indonesian
label, current-period figure, prior-period figure, English label - on one
physical line even when the label itself wraps visually, so a per-line
regex search is reliable without needing real table structure.

Field coverage is intentionally narrow: just what a headline "is this
company worth pitching" screen needs (revenue, gross/net profit, selling &
G&A expense, cash, total assets, liabilities, equity, sector) plus the raw
balance-sheet figures (current assets, current liabilities, total
liabilities, total equity) needed to compute standard health ratios -
Current Ratio, Debt-to-Equity Ratio, net margin, ROE - as real spreadsheet
formulas downstream (see intelligence.py). Employee count is deliberately
not attempted here - IDX's financial-statement XBRL doesn't reliably carry
it (it's an Annual Report / company-profile fact, not a financial-statement
line item), so any workbook built from this data leaves headcount as a
manual input rather than faking a source for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

import pdfplumber

from . import metadata

_NUMBER_RE = re.compile(r"\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?")
_SECTION_HEADER_RE = re.compile(r"^\[([\w]+)\]\s*(.+)$")


def _parse_number(token: str) -> float:
    token = token.strip()
    negative = token.startswith("(") or token.startswith("-")
    digits = token.strip("()").lstrip("-").replace(",", "")
    value = float(digits)
    return -value if negative else value


def _line_numbers(line: str) -> list[float]:
    return [_parse_number(m.group(0)) for m in _NUMBER_RE.finditer(line)]


def _find_line_values(
    text: str,
    *label_prefixes: str,
    prefer: str = "first",
    require: str | None = None,
    exclude: tuple[str, ...] = (),
) -> tuple[float | None, float | None]:
    """Lines starting with any of label_prefixes (case-insensitive) -> the
    first (or, with prefer="last", the last) matching line's first two
    numbers as (current_period, prior_period).

    prefer="last" exists for labels IDX's taxonomy reuses as a prefix of a
    longer line before the one actually wanted - e.g. "Jumlah laba (rugi)
    sebelum pajak..." (profit before tax) and "... dari operasi yang
    dilanjutkan" (from continuing operations) both start with "jumlah laba
    (rugi)" too, but the bare "Jumlah laba (rugi)" total line - the one
    actually wanted - always comes last in the statement's P&L walk.

    require/exclude filter by substring elsewhere on the same line, needed
    when the Indonesian label itself is identical across several lines and
    only the English half (which sits after the numbers, on the same
    physical line) tells them apart - e.g. total current liabilities, total
    non-current liabilities and total liabilities all render as a bare
    "Jumlah liabilitas <numbers> Total current/non-current/liabilities"
    line once the "jangka pendek/panjang" part of the label wraps away.
    """
    match: tuple[float | None, float | None] | None = None
    for line in text.split("\n"):
        lowered = line.strip().lower()
        for label in label_prefixes:
            if lowered.startswith(label):
                if require is not None and require not in lowered:
                    break
                if exclude and any(x in lowered for x in exclude):
                    break
                numbers = _line_numbers(line)
                if len(numbers) >= 2:
                    found = (numbers[0], numbers[1])
                elif len(numbers) == 1:
                    found = (numbers[0], None)
                else:
                    break
                if prefer == "first":
                    return found
                match = found
                break
    return match if match is not None else (None, None)


def _find_text_value(
    text: str, label: str, english_suffix: str, exclude: str | None = None
) -> str | None:
    """Extract the value of a "Label ... value ... English Suffix" line,
    e.g. "Sektor D. Consumer Non-Cyclicals Sector" -> "D. Consumer
    Non-Cyclicals" given label="Sektor", english_suffix="Sector".

    exclude guards against a *different*, longer field that happens to
    share both this label as a prefix and this suffix as an ending - e.g.
    "Industri utama entitas ... Entity main industry" starts with
    "Industri" and ends in "industry" just like the actual "Industri D23.
    ... Industry" (sector taxonomy code) field does.
    """
    pattern = re.compile(rf"^{re.escape(label)}\s+(.+?)\s+{re.escape(english_suffix)}\s*$", re.I)
    for line in text.split("\n"):
        stripped = line.strip()
        if exclude and exclude.lower() in stripped.lower():
            continue
        match = pattern.match(stripped)
        if match:
            return match.group(1).strip()
    return None


def _iter_sections(pdf) -> Iterator[tuple[str, str]]:
    """Yield (header_text, section_text) for each tagged section in the PDF,
    where section_text is every page's text from that header up to (not
    including) the next one."""
    current_header: str | None = None
    current_pages: list[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        first_line = text.split("\n", 1)[0] if text else ""
        match = _SECTION_HEADER_RE.match(first_line.strip())
        if match:
            if current_header is not None:
                yield current_header, "\n".join(current_pages)
            current_header = match.group(2)
            current_pages = [text]
        else:
            current_pages.append(text)
    if current_header is not None:
        yield current_header, "\n".join(current_pages)


@dataclass
class FinancialProfile:
    entity_name: str | None = None
    entity_code: str | None = None
    sektor: str | None = None
    subsektor: str | None = None
    industri: str | None = None
    jenis_laporan: str | None = None  # Diaudit / Tidak Diaudit
    pendapatan: float | None = None
    pendapatan_prior: float | None = None
    beban_pokok_penjualan: float | None = None
    laba_bruto: float | None = None
    beban_penjualan: float | None = None
    beban_administrasi: float | None = None
    laba_bersih: float | None = None
    laba_bersih_prior: float | None = None
    kas_setara_kas: float | None = None
    jumlah_aset_lancar: float | None = None
    jumlah_aset: float | None = None
    jumlah_liabilitas_jangka_pendek: float | None = None
    jumlah_liabilitas: float | None = None
    jumlah_ekuitas: float | None = None


def _fill_general_info(profile: FinancialProfile, text: str) -> None:
    profile.sektor = profile.sektor or _find_text_value(text, "Sektor", "Sector")
    profile.subsektor = profile.subsektor or _find_text_value(text, "Subsektor", "Subsector")
    profile.industri = profile.industri or _find_text_value(
        text, "Industri", "Industry", exclude="Industri utama entitas"
    )
    profile.jenis_laporan = profile.jenis_laporan or _find_text_value(
        text, "Jenis laporan atas laporan", "Type of report on financial"
    )


def _fill_balance_sheet(profile: FinancialProfile, text: str) -> None:
    kas, _ = _find_line_values(text, "kas dan setara kas")
    aset_lancar, _ = _find_line_values(text, "jumlah aset lancar")
    # "jumlah aset" also prefixes "Jumlah aset lancar" (current assets) and
    # "Jumlah aset tidak [lancar]" (non-current assets), both of which
    # appear earlier in the statement than the bare "Jumlah aset" grand
    # total this is actually after.
    aset, _ = _find_line_values(text, "jumlah aset", prefer="last")
    # The "jangka pendek"/"jangka panjang" part of the label wraps away in
    # IDX's renderer, so total current liabilities, total non-current
    # liabilities and total liabilities all appear as a bare "Jumlah
    # liabilitas <numbers> ..." line - only the English half (after the
    # numbers) tells them apart: "Total current", "Total non-current" and
    # "Total liabilities" respectively (see also "Total liabilities and
    # equity", excluded below by its Indonesian "dan" continuation).
    liabilitas_lancar, _ = _find_line_values(
        text, "jumlah liabilitas", require="current", exclude=("non-current",)
    )
    liabilitas, _ = _find_line_values(
        text, "jumlah liabilitas", exclude=("current", "liabilitas dan")
    )
    # Same wrapping behavior: "Jumlah ekuitas" appears once for equity
    # attributable to the parent, then again (last) for the grand total
    # including non-controlling interests - the one actually wanted.
    ekuitas, _ = _find_line_values(text, "jumlah ekuitas", prefer="last")

    profile.kas_setara_kas = profile.kas_setara_kas if profile.kas_setara_kas is not None else kas
    profile.jumlah_aset_lancar = (
        profile.jumlah_aset_lancar if profile.jumlah_aset_lancar is not None else aset_lancar
    )
    profile.jumlah_aset = profile.jumlah_aset if profile.jumlah_aset is not None else aset
    profile.jumlah_liabilitas_jangka_pendek = (
        profile.jumlah_liabilitas_jangka_pendek
        if profile.jumlah_liabilitas_jangka_pendek is not None
        else liabilitas_lancar
    )
    profile.jumlah_liabilitas = (
        profile.jumlah_liabilitas if profile.jumlah_liabilitas is not None else liabilitas
    )
    profile.jumlah_ekuitas = profile.jumlah_ekuitas if profile.jumlah_ekuitas is not None else ekuitas


def _fill_income_statement(profile: FinancialProfile, text: str) -> None:
    pendapatan, pendapatan_prior = _find_line_values(text, "penjualan dan pendapatan")
    beban_pokok, _ = _find_line_values(text, "beban pokok penjualan")
    laba_bruto, _ = _find_line_values(text, "jumlah laba bruto")
    beban_penjualan, _ = _find_line_values(text, "beban penjualan")
    # the label itself wraps ("Beban umum dan" carries the numbers,
    # "administrasi" continues alone on the next line), so only match on
    # the part that's actually on the same line as the numbers.
    beban_admin, _ = _find_line_values(text, "beban umum dan")
    # "Jumlah laba (rugi)" is also the prefix of "... sebelum pajak
    # penghasilan" (profit before tax) and "... dari operasi yang
    # dilanjutkan" (from continuing operations) earlier in the same
    # statement - the bare total line always comes last.
    laba_bersih, laba_bersih_prior = _find_line_values(text, "jumlah laba (rugi)", prefer="last")

    profile.pendapatan = pendapatan
    profile.pendapatan_prior = pendapatan_prior
    profile.beban_pokok_penjualan = beban_pokok
    profile.laba_bruto = laba_bruto
    profile.beban_penjualan = beban_penjualan
    profile.beban_administrasi = beban_admin
    profile.laba_bersih = laba_bersih
    profile.laba_bersih_prior = laba_bersih_prior


def extract_financial_profile(pdf_source) -> FinancialProfile:
    """Parse a downloaded IDX financial-report PDF into a FinancialProfile.

    pdf_source is anything pdfplumber.open() accepts (a path or file-like
    object). Fields that can't be found (template variation, a section
    that's missing for this report type) are left None rather than raising -
    callers decide how to handle partial data.
    """
    profile = FinancialProfile()
    profile.entity_name, profile.entity_code = metadata.extract_entity_metadata(pdf_source)

    with pdfplumber.open(pdf_source) as pdf:
        for header, text in _iter_sections(pdf):
            header_lower = header.lower()
            if "general information" in header_lower:
                _fill_general_info(profile, text)
            elif "financial position" in header_lower and profile.jumlah_aset is None:
                _fill_balance_sheet(profile, text)
            elif "profit or loss" in header_lower and profile.pendapatan is None:
                _fill_income_statement(profile, text)

    return profile
