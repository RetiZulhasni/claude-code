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


def _http_error(status_code: int):
    resp = MagicMock()
    resp.status_code = status_code
    return downloader.requests.exceptions.HTTPError(f"HTTP Error {status_code}", 0, resp)


class GuessPdfAttachmentTests(unittest.TestCase):
    def test_builds_expected_tw1_path(self):
        attachment = downloader.guess_pdf_attachment("AADI", 2026, "tw1")
        self.assertEqual(attachment["File_Name"], "FinancialStatement-2026-I-AADI.pdf")
        self.assertIn("/Laporan Keuangan Tahun 2026/TW1/AADI/", attachment["File_Path"])

    def test_builds_expected_tw2_path(self):
        attachment = downloader.guess_pdf_attachment("AADI", 2026, "tw2")
        self.assertEqual(attachment["File_Name"], "FinancialStatement-2026-II-AADI.pdf")

    def test_builds_expected_tw3_path(self):
        attachment = downloader.guess_pdf_attachment("AMIN", 2025, "tw3")
        self.assertEqual(attachment["File_Name"], "FinancialStatement-2025-III-AMIN.pdf")
        self.assertIn("/Laporan Keuangan Tahun 2025/TW3/AMIN/", attachment["File_Path"])

    def test_builds_expected_annual_path_using_audit_folder(self):
        # Confirmed against a real IDX URL: the annual report's folder is
        # "Audit", not "Tahunan" like the file suffix and every other
        # period's folder name would suggest.
        attachment = downloader.guess_pdf_attachment("AMIN", 2025, "tahunan")
        self.assertEqual(attachment["File_Name"], "FinancialStatement-2025-Tahunan-AMIN.pdf")
        self.assertIn("/Laporan Keuangan Tahun 2025/Audit/AMIN/", attachment["File_Path"])


class RequestWithRetryTests(unittest.TestCase):
    def test_does_not_retry_on_4xx(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = _http_error(404)
        session.request.return_value = resp

        with self.assertRaises(downloader.requests.exceptions.HTTPError):
            downloader._request_with_retry(session, "GET", "https://example.com/x")

        self.assertEqual(session.request.call_count, 1)

    def test_retries_on_non_4xx_error(self):
        session = MagicMock()
        resp_fail = MagicMock()
        resp_fail.raise_for_status.side_effect = _http_error(503)
        resp_ok = MagicMock()
        resp_ok.raise_for_status.return_value = None
        session.request.side_effect = [resp_fail, resp_ok]

        with patch.object(downloader.time, "sleep", return_value=None):
            result = downloader._request_with_retry(session, "GET", "https://example.com/x")

        self.assertIs(result, resp_ok)
        self.assertEqual(session.request.call_count, 2)


class ApiFallbackTests(unittest.TestCase):
    def test_falls_back_to_guessed_url_when_api_404s(self):
        session = MagicMock()

        def fake_request(method, url, **kwargs):
            resp = MagicMock()
            if url == downloader.BASE_URL:
                resp.raise_for_status.side_effect = _http_error(404)
            else:
                resp.raise_for_status.return_value = None
                resp.iter_content.return_value = [b"%PDF-1.4 fake content"]
            return resp

        session.request.side_effect = fake_request

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            results = downloader.run(
                kode_emiten="AADI", year=2026, periods=["tw1"], out_dir=out_dir, session=session
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file_name, "FinancialStatement-2026-I-AADI.pdf")
        api_calls = [c for c in session.request.call_args_list if c.args[1] == downloader.BASE_URL]
        self.assertEqual(len(api_calls), 1)

    def test_guessed_url_404_is_skipped_gracefully(self):
        session = MagicMock()

        def fake_request(method, url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.side_effect = _http_error(404)
            return resp

        session.request.side_effect = fake_request

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            results = downloader.run(
                kode_emiten="AADI", year=2026, periods=["tw1"], out_dir=out_dir, session=session
            )

        self.assertEqual(results, [])


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
