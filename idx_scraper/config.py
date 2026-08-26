"""Constants for talking to the IDX (Indonesia Stock Exchange) website."""

# The site has moved this endpoint before (legacy Umbraco path -> current
# Next.js "primary" API route). We try PRIMARY first and fall back to
# LEGACY so the scraper keeps working if IDX reverts or A/B tests routes.
PRIMARY_ENDPOINT = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
LEGACY_ENDPOINT = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetFinancialReport"
ENDPOINTS = (PRIMARY_ENDPOINT, LEGACY_ENDPOINT)

# Master list of every listed ticker (used when the caller asks for "all"
# companies instead of naming one).
SECURITIES_ENDPOINT = "https://www.idx.co.id/primary/StockData/GetSecuritiesStock"

# The JSON API rejects/empties out requests that don't carry cookies from a
# normal page load first. We hit these once per run to warm up a session
# before calling any of the endpoints above.
SESSION_WARMUP_URL = "https://www.idx.co.id/id"
SESSION_VALIDATE_URL = "https://www.idx.co.id/primary/home/GetIndexList"

# Files referenced by the API come back as host-relative paths
# (e.g. "Portals/0/StaticData/.../report.pdf").
FILE_HOST = "https://www.idx.co.id/"

# periode values accepted by the API. tw1/tw2/tw3 are interim quarterly
# reports, "audit" is the audited annual financial statement.
PERIODS = ("tw1", "tw2", "tw3", "audit")

# reportType: rdf = laporan keuangan (financial statements).
DEFAULT_REPORT_TYPE = "rdf"

# IDX itself only started publishing PDFs on this site from roughly the
# 2000s; used as the floor of a "--year all" range when a company's own
# listing year can't be determined.
FALLBACK_MIN_YEAR = 2000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Headers for the initial, plain page-load request that seeds cookies.
BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Headers for the JSON API calls themselves.
API_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
    "X-Requested-With": "XMLHttpRequest",
}

# Known ticker aliases so callers can pass a company name instead of a code.
COMPANY_TICKERS = {
    "adaro andalan indonesia": "AADI",
}
