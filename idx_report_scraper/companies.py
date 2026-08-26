"""Mapping between issuer names and their IDX ticker codes (kode emiten).

The IDX financial-report API is keyed on the 4-letter ticker code, not the
company name, so callers that only know the name need it resolved first.
Extend KNOWN_COMPANIES as more issuers are added to the scraper.
"""

from __future__ import annotations

KNOWN_COMPANIES = {
    "PT Adaro Andalan Indonesia Tbk": "AADI",
}


def resolve(company: str) -> str:
    """Resolve a company name or ticker code to its IDX ticker code.

    Accepts either a known company name (case-insensitive) or a ticker code
    (e.g. "AADI") passed straight through in upper case.
    """
    candidate = company.strip()

    if len(candidate) <= 5 and candidate.replace(".", "").isalpha():
        return candidate.upper()

    normalized = candidate.lower()
    for name, code in KNOWN_COMPANIES.items():
        if name.lower() == normalized:
            return code

    for name, code in KNOWN_COMPANIES.items():
        if normalized in name.lower():
            return code

    known = ", ".join(sorted(KNOWN_COMPANIES))
    raise ValueError(
        f"Tidak dapat menemukan kode emiten untuk '{company}'. "
        f"Perusahaan yang sudah dikenal: {known}. "
        "Gunakan --kode-emiten untuk memberikan kode ticker secara langsung."
    )
