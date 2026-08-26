"""Offline tests for CLI year-token expansion ("2026", "2020-2026", "all")."""

from idx_scraper.cli import parse_year_tokens


def test_single_year():
    assert parse_year_tokens(["2026"], listing_year=None, current_year=2026) == [2026]


def test_range_token():
    assert parse_year_tokens(["2020-2022"], listing_year=None, current_year=2026) == [
        2020,
        2021,
        2022,
    ]


def test_all_uses_listing_year_when_known():
    years = parse_year_tokens(["all"], listing_year=2024, current_year=2026)
    assert years == [2024, 2025, 2026]


def test_all_falls_back_to_min_year_when_unknown():
    years = parse_year_tokens(["all"], listing_year=None, current_year=2026)
    assert years[0] == 2000  # FALLBACK_MIN_YEAR
    assert years[-1] == 2026


def test_tokens_are_unioned_and_sorted():
    years = parse_year_tokens(["2026", "2020-2021"], listing_year=None, current_year=2026)
    assert years == [2020, 2021, 2026]
