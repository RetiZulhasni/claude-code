"""Offline tests for bulk multi-company orchestration: downloader.run() is
mocked out entirely, so these only exercise the ticker-file parsing and the
checkpoint/resume bookkeeping - no network, no real PDFs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from idx_report_scraper import bulk, downloader


class LoadTickersFromFileTests(unittest.TestCase):
    def test_reads_one_ticker_per_line_and_skips_noise(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tickers.txt"
            path.write_text("AADI\n\n# comment\nAALI\naadi\nBBCA\n", encoding="utf-8")
            self.assertEqual(bulk.load_tickers_from_file(path), ["AADI", "AALI", "BBCA"])

    def test_reads_first_column_of_csv_and_skips_header(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tickers.csv"
            path.write_text("Kode,Nama\nAADI,PT Adaro Andalan Indonesia Tbk\nBBCA,PT Bank BCA Tbk\n", encoding="utf-8")
            self.assertEqual(bulk.load_tickers_from_file(path), ["AADI", "BBCA"])


def _fake_download_result(kode_emiten: str) -> downloader.DownloadResult:
    return downloader.DownloadResult(
        kode_emiten=kode_emiten,
        year=2026,
        periode="tw1",
        file_name=f"FinancialStatement-2026-I-{kode_emiten}.pdf",
        source_url="https://www.idx.co.id/x.pdf",
        local_path=f"/tmp/{kode_emiten}.pdf",
        sha256="deadbeef",
        size_bytes=123,
        downloaded_at="2026-01-01T00:00:00+00:00",
    )


class RunAllTests(unittest.TestCase):
    def test_marks_each_ticker_done_and_writes_checkpoint(self):
        def fake_run(kode_emiten, year, periods, out_dir, session=None, use_api=True):
            return [_fake_download_result(kode_emiten)]

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch.object(downloader, "run", side_effect=fake_run):
                checkpoint = bulk.run_all(["AADI", "BBCA"], year=2026, out_dir=out_dir, delay_seconds=0)

            self.assertEqual(checkpoint["AADI"]["status"], "done")
            self.assertEqual(checkpoint["BBCA"]["status"], "done")
            saved = json.loads((out_dir / bulk.CHECKPOINT_FILENAME).read_text())
            self.assertEqual(saved, checkpoint)

    def test_resume_skips_tickers_already_done(self):
        calls = []

        def fake_run(kode_emiten, year, periods, out_dir, session=None, use_api=True):
            calls.append(kode_emiten)
            return [_fake_download_result(kode_emiten)]

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir).mkdir(parents=True, exist_ok=True)
            (out_dir / bulk.CHECKPOINT_FILENAME).write_text(
                json.dumps({"AADI": {"status": "done", "files": 1}}), encoding="utf-8"
            )

            with patch.object(downloader, "run", side_effect=fake_run):
                checkpoint = bulk.run_all(
                    ["AADI", "BBCA"], year=2026, out_dir=out_dir, resume=True, delay_seconds=0
                )

        self.assertEqual(calls, ["BBCA"])
        self.assertEqual(checkpoint["AADI"]["status"], "done")
        self.assertEqual(checkpoint["BBCA"]["status"], "done")

    def test_failed_ticker_is_recorded_and_retried_next_run(self):
        def failing_run(kode_emiten, year, periods, out_dir, session=None, use_api=True):
            if kode_emiten == "BBCA":
                raise RuntimeError("boom")
            return [_fake_download_result(kode_emiten)]

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)

            with patch.object(downloader, "run", side_effect=failing_run):
                checkpoint = bulk.run_all(["AADI", "BBCA"], year=2026, out_dir=out_dir, delay_seconds=0)

            self.assertEqual(checkpoint["AADI"]["status"], "done")
            self.assertEqual(checkpoint["BBCA"]["status"], "failed")
            self.assertIn("boom", checkpoint["BBCA"]["error"])

            # a second run (still resume=True) should retry only the failed one
            calls = []

            def fake_run(kode_emiten, year, periods, out_dir, session=None, use_api=True):
                calls.append(kode_emiten)
                return [_fake_download_result(kode_emiten)]

            with patch.object(downloader, "run", side_effect=fake_run):
                checkpoint = bulk.run_all(["AADI", "BBCA"], year=2026, out_dir=out_dir, delay_seconds=0)

            self.assertEqual(calls, ["BBCA"])
            self.assertEqual(checkpoint["BBCA"]["status"], "done")

    def test_no_resume_reprocesses_everything(self):
        calls = []

        def fake_run(kode_emiten, year, periods, out_dir, session=None, use_api=True):
            calls.append(kode_emiten)
            return [_fake_download_result(kode_emiten)]

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / bulk.CHECKPOINT_FILENAME).write_text(
                json.dumps({"AADI": {"status": "done", "files": 1}}), encoding="utf-8"
            )

            with patch.object(downloader, "run", side_effect=fake_run):
                bulk.run_all(["AADI", "BBCA"], year=2026, out_dir=out_dir, resume=False, delay_seconds=0)

        self.assertEqual(calls, ["AADI", "BBCA"])


if __name__ == "__main__":
    unittest.main()
