"""Constants for talking to the IDX (Indonesia Stock Exchange) website."""

# The site has moved this endpoint before (legacy Umbraco path -> current
# Next.js "primary" API route). We try PRIMARY first and fall back to
# LEGACY so the scraper keeps working if IDX reverts or A/B tests routes.
PRIMARY_ENDPOINT = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
LEGACY_ENDPOINT = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetFinancialReport"
ENDPOINTS = (PRIMARY_ENDPOINT, LEGACY_ENDPOINT)

# Files referenced by the API come back as host-relative paths
# (e.g. "Portals/0/StaticData/.../report.pdf").
FILE_HOST = "https://www.idx.co.id/"

# periode values accepted by the API. tw1/tw2/tw3 are interim quarterly
# reports, "audit" is the audited annual financial statement.
PERIODS = ("tw1", "tw2", "tw3", "audit")

# reportType: rdf = laporan keuangan (financial statements).
DEFAULT_REPORT_TYPE = "rdf"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
}

# Known ticker aliases so callers can pass a company name instead of a code.
COMPANY_TICKERS = {
    "adaro andalan indonesia": "AADI",
}
