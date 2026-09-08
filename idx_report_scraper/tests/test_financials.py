"""Offline tests for financial-statement extraction: pdfplumber.open() is
mocked out with fake page objects, so these lock in the line-matching
behavior (including the label-collision fixes) without needing a real PDF."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from idx_report_scraper import financials


class _FakePage:
    def __init__(self, text=""):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _page(*lines: str) -> _FakePage:
    return _FakePage("\n".join(lines))


GENERAL_INFO_PAGE = _page(
    "[1000000] General information",
    "Nama entitas Astra Agro Lestari Tbk Entity name",
    "Kode entitas AALI Entity code",
    "Industri utama entitas Umum / General Entity main industry",
    "Sektor D. Consumer Non-Cyclicals Sector",
    "Subsektor D2. Food & Beverage Subsector",
    "Industri D23. Agricultural Products Industry",
    "Jenis laporan atas laporan Diaudit / Audited Type of report on financial",
)

BALANCE_SHEET_PAGE = _page(
    "[1210000] Statement of financial position presented using current and",
    "Kas dan setara kas 3,236,012 2,089,508 Cash and cash equivalents",
    "Jumlah aset lancar 8,433,638 7,118,202 Total current assets",
    "Jumlah aset tidak 20,359,587 21,728,041 Total non-current",
    "Jumlah aset 28,793,225 28,846,243 Total assets",
    # "jangka pendek/panjang" wraps away, leaving three lines whose
    # Indonesian half is identically "Jumlah liabilitas <numbers>" - only
    # the trailing English half (current / non-current / liabilities)
    # distinguishes them, exactly as real AALI PDFs render this section.
    "Jumlah liabilitas 3,237,653 3,882,141 Total current",
    "Jumlah liabilitas 2,353,510 2,398,096 Total non-current",
    "Jumlah liabilitas 5,591,163 6,280,237 Total liabilities",
    "Jumlah ekuitas 22,641,918 22,016,045 Total equity",
    "Jumlah ekuitas 23,202,062 22,566,006 Total equity",
    "Jumlah liabilitas dan 28,793,225 28,846,243 Total liabilities and equity",
)

INCOME_STATEMENT_PAGE = _page(
    "[1321000] Statement of profit or loss and other comprehensive income, OCI",
    "Penjualan dan pendapatan 21,815,035 20,745,473 Sales and revenue",
    "Beban pokok penjualan dan ( 18,474,414 ) ( 17,974,493 ) Cost of sales and revenue",
    "Jumlah laba bruto 3,340,621 2,770,980 Total gross profit",
    "Beban penjualan ( 520,193 ) ( 611,396 ) Selling expenses",
    "Beban umum dan ( 1,161,949 ) ( 908,369 ) General and administrative",
    "Jumlah laba (rugi) sebelum 1,707,128 1,498,402 Total profit (loss) before",
    "Jumlah laba (rugi) dari 1,186,783 1,088,170 Total profit (loss) from",
    "Jumlah laba (rugi) 1,186,783 1,088,170 Total profit (loss)",
)


class ExtractFinancialProfileTests(unittest.TestCase):
    def _extract(self, pages):
        with patch.object(
            financials.metadata, "extract_entity_metadata", return_value=("Astra Agro Lestari Tbk", "AALI")
        ), patch.object(financials.pdfplumber, "open", return_value=_FakePdf(pages)):
            return financials.extract_financial_profile("fake.pdf")

    def test_general_info_fields(self):
        profile = self._extract([GENERAL_INFO_PAGE])
        self.assertEqual(profile.sektor, "D. Consumer Non-Cyclicals")
        self.assertEqual(profile.subsektor, "D2. Food & Beverage")
        self.assertEqual(profile.jenis_laporan, "Diaudit / Audited")

    def test_industri_does_not_collide_with_entity_main_industry(self):
        profile = self._extract([GENERAL_INFO_PAGE])
        self.assertEqual(profile.industri, "D23. Agricultural Products")

    def test_balance_sheet_total_assets_not_current_assets(self):
        profile = self._extract([BALANCE_SHEET_PAGE])
        self.assertEqual(profile.kas_setara_kas, 3236012.0)
        self.assertEqual(profile.jumlah_aset_lancar, 8433638.0)
        self.assertEqual(profile.jumlah_aset, 28793225.0)

    def test_balance_sheet_liabilities_and_equity_not_confused_with_subtotals(self):
        profile = self._extract([BALANCE_SHEET_PAGE])
        # Not the current (3,237,653) or non-current (2,353,510) subtotal,
        # and not the liabilities+equity grand total (28,793,225) either.
        self.assertEqual(profile.jumlah_liabilitas_jangka_pendek, 3237653.0)
        self.assertEqual(profile.jumlah_liabilitas, 5591163.0)
        # Not the parent-only equity figure (22,641,918) that precedes it.
        self.assertEqual(profile.jumlah_ekuitas, 23202062.0)

    def test_income_statement_headline_figures(self):
        profile = self._extract([INCOME_STATEMENT_PAGE])
        self.assertEqual(profile.pendapatan, 21815035.0)
        self.assertEqual(profile.pendapatan_prior, 20745473.0)
        self.assertEqual(profile.beban_pokok_penjualan, 18474414.0)
        self.assertEqual(profile.laba_bruto, 3340621.0)
        self.assertEqual(profile.beban_penjualan, 520193.0)
        self.assertEqual(profile.beban_administrasi, 1161949.0)

    def test_net_profit_not_profit_before_tax_or_continuing_ops(self):
        profile = self._extract([INCOME_STATEMENT_PAGE])
        self.assertEqual(profile.laba_bersih, 1186783.0)
        self.assertEqual(profile.laba_bersih_prior, 1088170.0)

    def test_missing_sections_leave_fields_none(self):
        profile = self._extract([_page("[9999999] Some Unrelated Section", "Foo Bar")])
        self.assertIsNone(profile.sektor)
        self.assertIsNone(profile.pendapatan)
        self.assertIsNone(profile.jumlah_aset)

    def test_combines_all_three_sections(self):
        profile = self._extract([GENERAL_INFO_PAGE, BALANCE_SHEET_PAGE, INCOME_STATEMENT_PAGE])
        self.assertEqual(profile.entity_code, "AALI")
        self.assertEqual(profile.jumlah_aset, 28793225.0)
        self.assertEqual(profile.laba_bersih, 1186783.0)


if __name__ == "__main__":
    unittest.main()
