"""Offline tests: exercise the parsing/orchestration logic without hitting
idx.co.id, using a fixture shaped like the real API response
(Results[].Attachments[].{File_Name,File_Path})."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from idx_report_scraper import companies, downloader

SAMPLE_RESPONSE = {
    "Results": [
        {
            "KodeEmiten": "AADI",
            "Tahun": "2026",
            "Periode": "tw2",
            "Attachments": [
                {
                    "File_Name": "AADI - Laporan Keuangan TW2 2026.pdf",
                    "File_Path": "https://idx.co.id/StaticData/AADI_TW2_2026.pdf",
                    "File_Size": 123456,
                    "File_Type": "pdf",
                },
                {
                    "File_Name": "AADI - Instance.xbrl",
                    "File_Path": "https://idx.co.id/StaticData/AADI_TW2_2026.xbrl",
                    "File_Size": 4096,
                    "File_Type": "xbrl",
                },
            ],
        }
    ]
}

EMPTY_RESPONSE = {"Results": []}


class ResolveCompanyTests(unittest.TestCase):
    def test_resolves_known_company_name(self):
        self.assertEqual(companies.resolve("PT Adaro Andalan Indonesia Tbk"), "AADI")

    def test_resolves_case_insensitively(self):
        self.assertEqual(companies.resolve("pt adaro andalan indonesia tbk"), "AADI")

    def test_passes_through_ticker_code(self):
        self.assertEqual(companies.resolve("aadi"), "AADI")

    def test_unknown_company_raises(self):
        with self.assertRaises(ValueError):
            companies.resolve("PT Perusahaan Tidak Dikenal Tbk")


class ExtractPdfAttachmentsTests(unittest.TestCase):
    def test_only_pdf_attachments_are_yielded(self):
        attachments = list(downloader.extract_pdf_attachments(SAMPLE_RESPONSE))
        self.assertEqual(len(attachments), 1)
        self.assertTrue(attachments[0]["File_Name"].endswith(".pdf"))

    def test_no_results_yields_nothing(self):
        self.assertEqual(list(downloader.extract_pdf_attachments(EMPTY_RESPONSE)), [])


class RunOrchestrationTests(unittest.TestCase):
    def test_run_downloads_pdfs_and_writes_manifest(self):
        session = MagicMock()

        def fake_request(method, url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if url == downloader.BASE_URL:
                periode = kwargs["params"]["periode"]
                resp.json.return_value = SAMPLE_RESPONSE if periode == "tw2" else EMPTY_RESPONSE
            else:
                resp.iter_content.return_value = [b"%PDF-1.4 fake content"]
            return resp

        session.request.side_effect = fake_request

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            results = downloader.run(
                kode_emiten="AADI",
                year=2026,
                periods=["tw1", "tw2"],
                out_dir=out_dir,
                session=session,
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].periode, "tw2")
            self.assertTrue(Path(results[0].local_path).exists())

            manifest_path = out_dir / "AADI" / "2026" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["file_name"], "AADI - Laporan Keuangan TW2 2026.pdf")


if __name__ == "__main__":
    unittest.main()
