# IDX Financial Report Scraper

Downloads financial/annual report PDFs published on
[idx.co.id](https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan)
for a given ticker, year, and reporting period, and saves them into an
organized folder structure.

## How it works

IDX's "Laporan Keuangan dan Tahunan" page is a single-page app backed by a
JSON API (no official public developer API is documented by IDX, but the
endpoint the page itself calls is stable and used by several existing open
scrapers):

```
GET https://www.idx.co.id/primary/ListedCompany/GetFinancialReport
    ?kodeEmiten=AADI&year=2026&periode=tw2&reportType=rdf
    &indexFrom=0&pageSize=100
```

The response lists report submissions, each with an `Attachments` array
containing the PDF file paths. This scraper:

1. Calls that endpoint per ticker/year/period (`idx_scraper/client.py`),
   falling back to the site's older `umbraco` route if the primary one
   ever stops responding.
2. Filters attachments to `.pdf` files and builds the full download URL.
3. Streams each PDF to disk under a predictable, resumable layout
   (`idx_scraper/downloader.py`):

   ```
   data/<KODE_EMITEN>/<YEAR>/<PERIODE>/<file_name>.pdf
   ```

   Existing files are skipped unless `--overwrite` is passed, so re-running
   the scraper is safe and only fetches what's new.
4. `idx_scraper/cli.py` is the orchestrator: loops over periods, logs
   progress, and never raises just because a report isn't published yet
   (an empty result for a quarter that hasn't closed is normal, not an
   error).

## Install

```bash
pip install -r requirements.txt
```

## Usage

PT Adaro Andalan Indonesia Tbk (ticker `AADI`), all periods for 2026:

```bash
python -m idx_scraper.cli --kode-emiten AADI --year 2026
```

You can also pass the company name (mapped to its ticker in
`idx_scraper/config.py::COMPANY_TICKERS`):

```bash
python -m idx_scraper.cli --kode-emiten "Adaro Andalan Indonesia" --year 2026
```

Single period, and preview without saving:

```bash
python -m idx_scraper.cli --kode-emiten AADI --year 2026 --periode tw2 --dry-run
```

Options:

| Flag | Meaning |
| --- | --- |
| `--kode-emiten` | Ticker (e.g. `AADI`) or known company name |
| `--year` | Fiscal year, e.g. `2026` |
| `--periode` | `tw1`, `tw2`, `tw3`, `audit`, or `all` (default) |
| `--report-type` | Default `rdf` (financial statements) |
| `--output-dir` | Root folder for downloads (default `./data`) |
| `--dry-run` | List what would be downloaded, don't save |
| `--overwrite` | Re-download files that already exist |
| `-v` | Verbose logging |

## About "tahun 2026"

IDX periods are named by when the reporting period *ends*, not when the
report is filed. For year=2026 you can expect:

- `tw1` (Jan-Mar 2026 interim report) — filed by ~end of April 2026
- `tw2` (Jan-Jun 2026 interim report) — filed by ~end of Jul/Aug 2026
- `tw3` (Jan-Sep 2026 interim report) — filed by ~end of Oct 2026
- `audit` (full-year audited statement) — normally filed ~Q1 of the
  *following* year (2027), so it usually won't exist yet under `year=2026`
  until then.

Running with `--periode all` is safe either way: periods that aren't
published yet simply come back empty and are logged as such.

## Tests

Offline unit tests mock the HTTP layer and check the response-parsing and
PDF-filtering logic without needing network access:

```bash
pip install pytest
pytest tests/ -v
```

## Known limitation of this dev environment

This scraper was authored and unit-tested in a sandboxed session whose
outbound network access to `idx.co.id` is blocked by policy, so the live
API call could not be exercised end-to-end here. Run it from a normal
machine/CI with outbound internet access; if IDX has changed the endpoint
shape since, the parsing in `client.py::_extract_attachments` /
`_pick` is written defensively (multiple key-name fallbacks) to reduce the
blast radius, and `--dry-run -v` is the fastest way to check what a fresh
run actually gets back.
