"""HTTP client for the idx.co.id financial report listing API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from idx_scraper.config import DEFAULT_HEADERS, ENDPOINTS, FILE_HOST

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportFile:
    """One downloadable PDF attachment from a financial report submission."""

    kode_emiten: str
    year: str
    periode: str
    file_name: str
    file_path: str
    file_modified: str | None

    @property
    def download_url(self) -> str:
        return urljoin(FILE_HOST, self.file_path.lstrip("/"))


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _extract_attachments(payload: Any) -> Iterable[dict]:
    """Walk the API's response shape defensively.

    The known shape is ``{"Results": [{"Attachments": [...]}, ...]}`` but we
    tolerate a bare list of attachments too, since IDX has changed this
    envelope before without notice.
    """
    if isinstance(payload, dict) and "Results" in payload:
        for result in payload["Results"] or []:
            yield from result.get("Attachments") or []
    elif isinstance(payload, list):
        yield from payload


def _pick(attachment: dict, *candidate_keys: str) -> str | None:
    for key in candidate_keys:
        value = attachment.get(key)
        if value:
            return value
    return None


class IDXClient:
    """Fetches the list of financial-report PDF attachments for a ticker."""

    def __init__(self, session: requests.Session | None = None, timeout: float = 20.0):
        self.session = session or _build_session()
        self.timeout = timeout

    def fetch_report_files(
        self,
        kode_emiten: str,
        year: int | str,
        periode: str,
        report_type: str = "rdf",
        page_size: int = 100,
    ) -> list[ReportFile]:
        """Return the PDF attachments IDX lists for one ticker/year/period.

        Returns an empty list (never raises) when the report simply hasn't
        been published yet for that period -- that's the normal case for a
        quarter that hasn't closed, not an error.
        """
        params = {
            "indexFrom": 0,
            "pageSize": page_size,
            "year": str(year),
            "reportType": report_type,
            "periode": periode,
            "kodeEmiten": kode_emiten,
        }

        last_error: Exception | None = None
        for endpoint in ENDPOINTS:
            try:
                response = self.session.get(endpoint, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Endpoint %s failed for %s: %s", endpoint, params, exc)
                last_error = exc
                continue

            files = []
            for attachment in _extract_attachments(payload):
                file_path = _pick(attachment, "File_Path", "FilePath", "Path")
                if not file_path or not file_path.lower().endswith(".pdf"):
                    continue
                file_name = _pick(
                    attachment, "File_Name", "FileName", "Nama_File"
                ) or file_path.rsplit("/", 1)[-1]
                files.append(
                    ReportFile(
                        kode_emiten=kode_emiten,
                        year=str(year),
                        periode=periode,
                        file_name=file_name,
                        file_path=file_path,
                        file_modified=_pick(attachment, "File_Modified", "FileModified"),
                    )
                )
            logger.info(
                "%s %s %s: %d PDF(s) via %s", kode_emiten, year, periode, len(files), endpoint
            )
            return files

        raise RuntimeError(
            f"All IDX endpoints failed for {params}: {last_error}"
        ) from last_error
