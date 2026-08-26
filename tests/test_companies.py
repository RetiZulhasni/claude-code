"""Offline tests for the securities-list (companies) parsing logic."""

from unittest.mock import MagicMock

from idx_scraper.companies import Company, list_companies


SAMPLE_PAYLOAD = {
    "data": [
        {
            "Code": "aadi",
            "Name": "Adaro Andalan Indonesia Tbk.",
            "Shares": 1000000,
            "ListingDate": "2024-12-05T00:00:00",
            "ListingBoard": "Utama",
        },
        {
            "Code": "ADRO",
            "Name": "Alamtri Resources Indonesia Tbk.",
            "ListingDate": "2008-07-16T00:00:00",
            "ListingBoard": "Utama",
        },
        {"Code": None, "Name": "Skipped row with no code"},
    ],
    "recordsTotal": 3,
    "recordsFiltered": 3,
}


def test_list_companies_parses_and_uppercases_codes():
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = SAMPLE_PAYLOAD
    response.raise_for_status.return_value = None
    session.get.return_value = response

    companies = list_companies(session)

    assert [c.code for c in companies] == ["AADI", "ADRO"]
    assert companies[0].name == "Adaro Andalan Indonesia Tbk."


def test_company_listing_year_parses_iso_date():
    company = Company(code="AADI", name="x", listing_date="2024-12-05T00:00:00")
    assert company.listing_year == 2024


def test_company_listing_year_none_when_missing():
    company = Company(code="AADI", name="x", listing_date=None)
    assert company.listing_year is None
