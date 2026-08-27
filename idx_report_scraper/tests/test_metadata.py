"""Offline tests for entity metadata extraction: no real PDF is opened,
pdfplumber.open() is mocked out with fake page objects so the label-matching
logic (table-first, text-fallback) can be verified deterministically."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from idx_report_scraper import metadata


class _FakePage:
    def __init__(self, tables=None, text=""):
        self._tables = tables or []
        self._text = text

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class ExtractEntityMetadataTests(unittest.TestCase):
    def test_extracts_from_table(self):
        page = _FakePage(
            tables=[
                [
                    ["Nama Entitas", "PT Adaro Andalan Indonesia Tbk"],
                    ["Kode Entitas", "AADI"],
                ]
            ]
        )
        with patch.object(metadata.pdfplumber, "open", return_value=_FakePdf([page])):
            company, code = metadata.extract_entity_metadata("fake.pdf")
        self.assertEqual(company, "PT Adaro Andalan Indonesia Tbk")
        self.assertEqual(code, "AADI")

    def test_extracts_nama_emiten_label_variant(self):
        # The label actually used on AADI's own TW1 2026 cover page
        # ("Nomor Surat / Nama Emiten / Kode Emiten / Perihal"), not
        # "Nama Entitas" - both must be recognized.
        page = _FakePage(
            tables=[
                [
                    ["Nomor Surat", "AADI/BEI/V/2026"],
                    ["Nama Emiten", "PT Adaro Andalan Indonesia Tbk"],
                    ["Kode Emiten", "AADI"],
                    ["Perihal", "Penyampaian Laporan Keuangan Interim"],
                ]
            ]
        )
        with patch.object(metadata.pdfplumber, "open", return_value=_FakePdf([page])):
            company, code = metadata.extract_entity_metadata("fake.pdf")
        self.assertEqual(company, "PT Adaro Andalan Indonesia Tbk")
        self.assertEqual(code, "AADI")

    def test_falls_back_to_text_when_no_table_match(self):
        page = _FakePage(
            tables=[],
            text="Nama Entitas: PT Adaro Andalan Indonesia Tbk\nKode Entitas: AADI\n",
        )
        with patch.object(metadata.pdfplumber, "open", return_value=_FakePdf([page])):
            company, code = metadata.extract_entity_metadata("fake.pdf")
        self.assertEqual(company, "PT Adaro Andalan Indonesia Tbk")
        self.assertEqual(code, "AADI")

    def test_returns_none_when_nothing_found(self):
        page = _FakePage(tables=[], text="isi laporan tidak relevan")
        with patch.object(metadata.pdfplumber, "open", return_value=_FakePdf([page])):
            company, code = metadata.extract_entity_metadata("fake.pdf")
        self.assertIsNone(company)
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
