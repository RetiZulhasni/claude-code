"""Offline tests: exercise the parsing/orchestration logic without hitting
idx.co.id, using a fixture shaped like the real API response - a bare JSON
array of report entries (not a {"Results": [...]} envelope), each with
NamaEmiten/KodeEmiten and Attachments[].{File_Name,File_Path}, where
File_Path is a site-relative path rather than a full URL."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from idx_report_scraper import companies, downloader

SAMPLE_RESPONSE = [
    {
        "KodeEmiten": "AADI",
        "NamaEmiten": "PT Adaro Andalan Indonesia Tbk",
        "Report_Year": "2026",
        "Report_Period": "TW2",
        "Attachments": [
            {
                "File_Name": "AADI - Laporan Keuangan TW2 2026.pdf",
                "File_Path": "/Portals/0/StaticData/Laporan Keuangan Tahun 2026//TW2/AADI/AADI - Laporan Keuangan TW2 2026.pdf",
                "File_Size": 123456,
                "File_Type": ".pdf",
            },
            {
                "File_Name": "AADI - Instance.xbrl",
                "File_Path": "/Portals/0/StaticData/Laporan Keuangan Tahun 2026//TW2/AADI/AADI - Instance.xbrl",
                "File_Size": 4096,
                "File_Type": ".xbrl",
            },
        ],
    }
]

EMPTY_RESPONSE = []


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

    def test_carries_entity_identity_from_parent_result(self):
        attachments = list(downloader.extract_pdf_attachments(SAMPLE_RESPONSE))
        self.assertEqual(attachments[0]["_entity_name"], "PT Adaro Andalan Indonesia Tbk")
        self.assertEqual(attachments[0]["_entity_code"], "AADI")

    def test_no_results_yields_nothing(self):
        self.assertEqual(list(downloader.extract_pdf_attachments(EMPTY_RESPONSE)), [])

    def test_accepts_legacy_results_envelope(self):
        wrapped = {"Results": SAMPLE_RESPONSE}
        self.assertEqual(
            list(downloader.extract_pdf_attachments(wrapped)),
            list(downloader.extract_pdf_attachments(SAMPLE_RESPONSE)),
        )


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

        # The API already supplies NamaEmiten/KodeEmiten per report, so
        # download_pdf() shouldn't need to fall back to PDF parsing at all;
        # a fallback that's actually invoked here means that stopped holding.
        with TemporaryDirectory() as tmp, patch.object(
            downloader.metadata,
            "extract_entity_metadata",
            side_effect=AssertionError("PDF metadata fallback should not run when the API already has it"),
        ):
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
            self.assertEqual(results[0].entity_name, "PT Adaro Andalan Indonesia Tbk")
            self.assertEqual(results[0].entity_code, "AADI")

            attachment_path = SAMPLE_RESPONSE[0]["Attachments"][0]["File_Path"]
            expected_url = downloader.DOWNLOAD_BASE_URL + quote(attachment_path, safe="/")
            self.assertEqual(results[0].source_url, expected_url)
            self.assertNotIn(" ", results[0].source_url)

            manifest_path = out_dir / "AADI" / "2026" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["file_name"], "AADI - Laporan Keuangan TW2 2026.pdf")
            self.assertEqual(manifest[0]["entity_code"], "AADI")

    def test_falls_back_to_pdf_metadata_when_api_omits_identity(self):
        session = MagicMock()
        attachment = {
            "File_Name": "AADI - Laporan Keuangan TW2 2026.pdf",
            "File_Path": "/Portals/0/StaticData/AADI_TW2_2026.pdf",
        }

        def fake_request(method, url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.iter_content.return_value = [b"%PDF-1.4 fake content"]
            return resp

        session.request.side_effect = fake_request

        with TemporaryDirectory() as tmp, patch.object(
            downloader.metadata,
            "extract_entity_metadata",
            return_value=("PT Adaro Andalan Indonesia Tbk", "AADI"),
        ) as mock_extract:
            result = downloader.download_pdf(
                attachment, Path(tmp), session, kode_emiten="AADI", year=2026, periode="tw2"
            )

        mock_extract.assert_called_once()
        self.assertEqual(result.entity_name, "PT Adaro Andalan Indonesia Tbk")
        self.assertEqual(result.entity_code, "AADI")


if __name__ == "__main__":
    unittest.main()
