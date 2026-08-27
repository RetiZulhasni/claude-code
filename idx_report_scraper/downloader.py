"""Core automation for pulling financial-report PDFs from idx.co.id.

Pipeline, one step per function so each stage can be tested and retried
independently:

    fetch_report()            -> raw JSON from the IDX financial-report API
    extract_pdf_attachments() -> just the PDF entries from that JSON
    download_pdf()            -> one attachment saved to disk, with retries
    run()                     -> orchestrates the above across periods and
                                  writes a manifest.json describing the result

Endpoint and JSON field names (Results[].Attachments[].File_Name /
File_Path) were confirmed against a public IDX scraper implementation, not
guessed from documentation, since idx.co.id does not publish an API
reference. If IDX changes the response shape, fetch_report() will surface
the raw payload so the mismatch is easy to diagnose.

idx.co.id sits behind Cloudflare, which rejects plain `requests` calls
outright (a 403 "Attention Required" page) based on the TLS handshake
fingerprint, regardless of what User-Agent/Referer headers are sent -
Python's stock TLS stack doesn't match a real Chrome fingerprint. curl_cffi
is used instead of `requests` because it reproduces a real browser's TLS
fingerprint (JA3), not just its headers; its Session/Response API is
otherwise a drop-in match for `requests` (same method names, .json(),
.iter_content(), .raise_for_status()).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import quote

from curl_cffi import requests

from . import metadata

logger = logging.getLogger("idx_report_scraper")

BASE_URL = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetFinancialReport"
DOWNLOAD_BASE_URL = "https://www.idx.co.id"
VALID_PERIODS = ("tw1", "tw2", "tw3", "tahunan")
DEFAULT_PERIODS = VALID_PERIODS

# impersonate="chrome" (set on the Session) already supplies a matching
# User-Agent/sec-ch-ua for the TLS fingerprint being replicated - only the
# headers a real browser adds on top of that for this specific AJAX call
# need to be listed here.
HEADERS = {
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 2


@dataclass
class DownloadResult:
    kode_emiten: str
    year: int
    periode: str
    file_name: str
    source_url: str
    local_path: str
    sha256: str
    size_bytes: int
    downloaded_at: str
    entity_name: str | None = None
    entity_code: str | None = None


def _request_with_retry(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500:
                # a 4xx won't change on retry (wrong URL, no such report) -
                # retrying it just burns time the caller may want to spend
                # on a fallback instead.
                raise
            if attempt == MAX_ATTEMPTS:
                break
            wait = BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Request ke %s gagal (percobaan %d/%d): %s. Mencoba lagi dalam %ds.",
                url,
                attempt,
                MAX_ATTEMPTS,
                exc,
                wait,
            )
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def _warm_up_session(session: requests.Session) -> None:
    """Visit the report listing page once so idx.co.id issues its session
    cookie before we call the AJAX endpoint directly - hitting the API
    cold (no referring-page cookie) is what a real browser never does, and
    is a likely reason IDX's side rejects it with a 403. Best-effort: if
    this fails we still attempt the API call, since not every deployment
    requires it.
    """
    try:
        session.get(HEADERS["Referer"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        logger.warning("Gagal warm-up sesi ke halaman IDX (%s): %s", HEADERS["Referer"], exc)


def fetch_report(
    kode_emiten: str,
    year: int,
    periode: str,
    session: requests.Session,
    report_type: str = "rdf",
    page_size: int = 10,
) -> dict:
    """Call the IDX financial-report API for one issuer/year/period."""
    if periode not in VALID_PERIODS:
        raise ValueError(f"periode harus salah satu dari {VALID_PERIODS}, dapat '{periode}'")

    params = {
        "indexFrom": 0,
        "pageSize": page_size,
        "year": year,
        "reportType": report_type,
        "periode": periode,
        "kodeEmiten": kode_emiten,
    }
    response = _request_with_retry(session, "GET", BASE_URL, params=params, headers=HEADERS)
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Respons IDX untuk {kode_emiten} {year}/{periode} bukan JSON valid: {exc}\n"
            f"Cuplikan respons: {response.text[:500]!r}"
        ) from exc


# Folder/filename convention confirmed against real IDX URLs (AMIN 2025
# TW1-TW3 and annual, AADI 2025/2026 TW1): .../Laporan Keuangan Tahun
# {year}/{folder}/{KODE}/FinancialStatement-{year}-{suffix}-{KODE}.pdf.
# The annual report's folder is "Audit" (not "Tahunan" like the file
# suffix uses) - easy to miss since every other period's folder name
# matches its suffix.
_STATIC_DATA_PREFIX = (
    "/Portals/0/StaticData/ListedCompanies/Corporate_Actions/New_Info_JSX/"
    "Jenis_Informasi/01_Laporan_Keuangan/02_Soft_Copy_Laporan_Keuangan/"
)
_PERIOD_FOLDER = {"tw1": "TW1", "tw2": "TW2", "tw3": "TW3", "tahunan": "Audit"}
_PERIOD_SUFFIX = {"tw1": "I", "tw2": "II", "tw3": "III", "tahunan": "Tahunan"}


def guess_pdf_attachment(kode_emiten: str, year: int, periode: str) -> dict:
    """Predict the canonical FinancialStatement PDF path IDX uses, for use
    when the GetFinancialReport AJAX endpoint can't be reached at all.

    This is a best-effort fallback, not a replacement for the API: it only
    covers the single standardized filename, while a report can also carry
    extra PDF variants (e.g. a company-named copy) that only the API's JSON
    lists. Whether the guessed URL actually exists is only known once
    download_pdf() requests it.
    """
    folder = _PERIOD_FOLDER[periode]
    suffix = _PERIOD_SUFFIX[periode]
    file_name = f"FinancialStatement-{year}-{suffix}-{kode_emiten}.pdf"
    file_path = f"{_STATIC_DATA_PREFIX}/Laporan Keuangan Tahun {year}/{folder}/{kode_emiten}/{file_name}"
    return {"File_Name": file_name, "File_Path": file_path}


def extract_pdf_attachments(data) -> Iterator[dict]:
    """Yield only the PDF attachments out of a fetch_report() payload.

    The API's real response is a bare JSON array of report entries, not the
    {"Results": [...]} envelope IDX's older static-scraper references
    assumed - but that wrapped shape is accepted too in case a different
    report type or a future API revision goes back to it. Each yielded
    attachment carries the parent entry's NamaEmiten/KodeEmiten under
    _entity_name/_entity_code, since the API already gives us that for
    free - no need to open the PDF just to find out whose report it is.

    A company that files a correction/restatement for a period it already
    reported can show up as a second entry with the same File_Name - only
    the one with the latest File_Modified is kept, so a corrected report
    always wins over the one it superseded rather than whichever happened
    to be listed first.
    """
    results = data if isinstance(data, list) else (data or {}).get("Results", []) or []
    by_file_name: dict[str, dict] = {}
    for result in results:
        entity_name = result.get("NamaEmiten")
        entity_code = result.get("KodeEmiten")
        for attachment in result.get("Attachments", []) or []:
            file_name = attachment.get("File_Name", "") or ""
            file_path = attachment.get("File_Path", "") or ""
            if not (file_name.lower().endswith(".pdf") or file_path.lower().endswith(".pdf")):
                continue
            enriched = {**attachment, "_entity_name": entity_name, "_entity_code": entity_code}
            # fall back to File_Path when File_Name is missing, so two
            # attachments that both lack a name don't collide on "" and
            # wrongly collapse into one.
            key = file_name or file_path
            existing = by_file_name.get(key)
            if existing is None or _is_newer(enriched, existing):
                by_file_name[key] = enriched
    yield from by_file_name.values()


def _is_newer(candidate: dict, existing: dict) -> bool:
    # File_Modified is a fixed-width ISO-ish timestamp (e.g.
    # "2026-04-30T16:51:25.623"), so a plain string comparison already
    # sorts chronologically - no need to parse it.
    return (candidate.get("File_Modified") or "") > (existing.get("File_Modified") or "")


def download_pdf(
    attachment: dict,
    dest_dir: Path,
    session: requests.Session,
    kode_emiten: str,
    year: int,
    periode: str,
) -> DownloadResult:
    file_path = attachment["File_Path"]
    # File_Path is a site-relative path (e.g. "/Portals/0/...pdf"), not a
    # full URL - quote() only escapes the raw spaces/special characters IDX
    # embeds in it (folder names like "Laporan Keuangan Tahun 2026"),
    # leaving the "/" separators (and its own doubled "//") intact.
    url = file_path if file_path.startswith("http") else DOWNLOAD_BASE_URL + quote(file_path, safe="/")
    file_name = attachment.get("File_Name") or url.rsplit("/", 1)[-1]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file_name

    response = _request_with_retry(session, "GET", url, headers=HEADERS, stream=True)
    sha256 = hashlib.sha256()
    size = 0
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            f.write(chunk)
            sha256.update(chunk)
            size += len(chunk)

    entity_name = attachment.get("_entity_name")
    entity_code = attachment.get("_entity_code")
    if not (entity_name and entity_code):
        try:
            pdf_name, pdf_code = metadata.extract_entity_metadata(dest_path)
            entity_name = entity_name or pdf_name
            entity_code = entity_code or pdf_code
        except Exception as exc:
            # PDF templates vary across reports/years; a cover page that
            # doesn't parse shouldn't fail the download itself.
            logger.warning("Gagal mengekstrak metadata entitas dari %s: %s", dest_path, exc)

    return DownloadResult(
        kode_emiten=kode_emiten,
        year=year,
        periode=periode,
        file_name=file_name,
        source_url=url,
        local_path=str(dest_path),
        sha256=sha256.hexdigest(),
        size_bytes=size,
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        entity_name=entity_name,
        entity_code=entity_code,
    )


def _is_404(exc: Exception) -> bool:
    return getattr(getattr(exc, "response", None), "status_code", None) == 404


def _list_attachments(
    kode_emiten: str, year: int, periode: str, session: requests.Session, use_api: bool = True
) -> list[dict]:
    """fetch_report() + extract_pdf_attachments(), falling back to a
    guessed direct PDF URL if the AJAX endpoint itself 404s (as opposed to
    returning an empty result for a period with no report yet).

    With use_api=False the AJAX endpoint is skipped entirely and every
    period goes straight to the guessed URL - useful when that endpoint is
    being unreliable on its own (404s one moment, a flat-out 403 the next)
    while the static file path it's meant to discover has been directly
    verified to be correct.
    """
    if not use_api:
        return [guess_pdf_attachment(kode_emiten, year, periode)]

    try:
        data = fetch_report(kode_emiten, year, periode, session)
        return list(extract_pdf_attachments(data))
    except requests.exceptions.HTTPError as exc:
        if not _is_404(exc):
            raise
        logger.warning(
            "Endpoint API 404 untuk periode %s; memakai pola URL unduhan langsung sebagai fallback "
            "(hanya menemukan file standar - varian nama lain bisa terlewat).",
            periode,
        )
        return [guess_pdf_attachment(kode_emiten, year, periode)]


def run(
    kode_emiten: str,
    year: int,
    periods: Iterable[str] = DEFAULT_PERIODS,
    out_dir: Path = Path("downloads"),
    session: requests.Session | None = None,
    use_api: bool = True,
) -> list[DownloadResult]:
    """Fetch + download every PDF financial report for kode_emiten/year.

    Periods with no published report yet (e.g. a quarter that hasn't closed)
    are logged and skipped rather than treated as errors, since that is the
    expected state for the current fiscal year.

    use_api=False skips the GetFinancialReport AJAX call entirely and goes
    straight to the guessed static PDF URL for every period - use this when
    that endpoint itself is being unreliable (404s one moment, 403s the
    next) rather than just reporting an empty period.
    """
    owns_session = session is None
    session = session or requests.Session(impersonate="chrome")
    if use_api:
        _warm_up_session(session)
    results: list[DownloadResult] = []

    try:
        for periode in periods:
            logger.info("Mengambil laporan %s tahun %s periode %s ...", kode_emiten, year, periode)
            attachments = _list_attachments(kode_emiten, year, periode, session, use_api=use_api)

            if not attachments:
                logger.info("Tidak ada PDF untuk periode %s (belum terbit atau tidak tersedia).", periode)
                continue

            dest_dir = out_dir / kode_emiten / str(year) / periode
            for attachment in attachments:
                logger.info("Mengunduh %s", attachment.get("File_Name"))
                try:
                    result = download_pdf(attachment, dest_dir, session, kode_emiten, year, periode)
                except requests.exceptions.HTTPError as exc:
                    if not _is_404(exc):
                        raise
                    logger.info(
                        "%s tidak ditemukan (404), dilewati.", attachment.get("File_Name")
                    )
                    continue
                results.append(result)
    finally:
        if owns_session:
            session.close()

    manifest_path = out_dir / kode_emiten / str(year) / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)
    logger.info("Manifest ditulis ke %s (%d file)", manifest_path, len(results))

    return results
