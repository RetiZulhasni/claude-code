"""Offline tests for response parsing -- no network access required."""

from unittest.mock import MagicMock

from idx_scraper.client import IDXClient, _extract_attachments


SAMPLE_PAYLOAD = {
    "Results": [
        {
            "Attachments": [
                {
                    "File_Path": "Portals/0/StaticData/FinancialReport/AADI_TW2_2026.pdf",
                    "File_Name": "AADI_TW2_2026.pdf",
                    "File_Modified": "2026-07-30T00:00:00",
                },
                {
                    # Non-PDF attachment should be filtered out.
                    "File_Path": "Portals/0/StaticData/FinancialReport/cover.xlsx",
                    "File_Name": "cover.xlsx",
                },
            ]
        }
    ]
}


def test_extract_attachments_walks_results():
    attachments = list(_extract_attachments(SAMPLE_PAYLOAD))
    assert len(attachments) == 2


def test_extract_attachments_accepts_bare_list():
    bare = SAMPLE_PAYLOAD["Results"][0]["Attachments"]
    assert list(_extract_attachments(bare)) == bare


def test_fetch_report_files_filters_to_pdf_and_builds_url():
    client = IDXClient(session=MagicMock())
    response = MagicMock()
    response.json.return_value = SAMPLE_PAYLOAD
    response.raise_for_status.return_value = None
    client.session.get.return_value = response

    files = client.fetch_report_files(kode_emiten="AADI", year=2026, periode="tw2")

    assert len(files) == 1
    report = files[0]
    assert report.file_name == "AADI_TW2_2026.pdf"
    assert report.download_url == (
        "https://www.idx.co.id/Portals/0/StaticData/FinancialReport/AADI_TW2_2026.pdf"
    )


def test_fetch_report_files_returns_empty_when_not_published():
    client = IDXClient(session=MagicMock())
    response = MagicMock()
    response.json.return_value = {"Results": []}
    response.raise_for_status.return_value = None
    client.session.get.return_value = response

    files = client.fetch_report_files(kode_emiten="AADI", year=2026, periode="tw3")
    assert files == []
