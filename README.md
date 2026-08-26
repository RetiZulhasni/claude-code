# IDX Financial Report Scraper

Downloads financial/annual report PDFs published on
[idx.co.id](https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan)
for one ticker, a handful of tickers, or **every listed company**, across
one year, a year range, or **every year since listing** — and saves them
into an organized, resumable folder structure.

## How it works

IDX's "Laporan Keuangan dan Tahunan" page is a single-page app backed by
JSON APIs (no official public developer API is documented by IDX, but the
endpoints the page itself calls are stable and used by several existing
open scrapers):

```
GET https://www.idx.co.id/primary/ListedCompany/GetFinancialReport
    ?kodeEmiten=AADI&year=2026&periode=tw2&reportType=rdf
    &indexFrom=0&pageSize=100

GET https://www.idx.co.id/primary/StockData/GetSecuritiesStock
    ?start=0&length=9999&code=&sector=&board=
```

The first lists report submissions for one ticker/year/period, each with
an `Attachments` array of PDF file paths. The second is the master list of
every ticker IDX has listed, used when you ask for "all" companies instead
of naming one. Both endpoints only reliably respond once a session carries
cookies from a normal page load — cold requests can come back
empty/blocked even with correct params.

The pieces:

1. `idx_scraper/session.py` — warms up a `requests.Session` (page load +
   cookie capture) once per run, and mounts retry-with-backoff for
   transient 429/5xx errors. Everything else reuses this session.
2. `idx_scraper/companies.py` — calls `GetSecuritiesStock` to resolve
   `--kode-emiten all` into every listed ticker (optionally filtered by
   `--sector`/`--board`), and exposes each company's listing year so
   `--year all` knows where to start.
3. `idx_scraper/client.py` — calls `GetFinancialReport` per
   ticker/year/period, falling back to the site's older `umbraco` route if
   the primary one ever stops responding, and filters attachments down to
   `.pdf` files.
4. `idx_scraper/downloader.py` — streams each PDF to disk under a
   predictable layout:

   ```
   data/<KODE_EMITEN>/<YEAR>/<PERIODE>/<file_name>.pdf
   ```

   Existing files are skipped unless `--overwrite` is passed, so
   re-running (or resuming an interrupted large run) is safe and only
   fetches what's new.
5. `idx_scraper/cli.py` — the orchestrator: expands `--kode-emiten`/`--year`
   into concrete (company, year, period) jobs, runs them sequentially or
   across a thread pool, applies a politeness delay between requests, and
   writes a CSV manifest so a large run stays auditable. It never treats
   "report not published yet" as an error.

## Install

```bash
pip install -r requirements.txt
```

## Usage

One company, all periods, one year:

```bash
python -m idx_scraper.cli --kode-emiten AADI --year 2026
```

You can also pass the company name (mapped to its ticker in
`idx_scraper/config.py::COMPANY_TICKERS`):

```bash
python -m idx_scraper.cli --kode-emiten "Adaro Andalan Indonesia" --year 2026
```

Several named companies, a year range, one period, preview only:

```bash
python -m idx_scraper.cli --kode-emiten AADI ADRO --year 2020-2026 --periode tw2 --dry-run
```

**Every listed company**, one year, every period:

```bash
python -m idx_scraper.cli --kode-emiten all --year 2026
```

**Everything IDX has** — every company, every year since each company's own
listing date, every period — run with modest concurrency:

```bash
python -m idx_scraper.cli --kode-emiten all --year all --max-workers 4
```

⚠️ That last form is heavy: ~900+ listed companies × up to ~25 years ×
4 periods is tens of thousands of listing requests before any PDF is even
downloaded. Prefer narrowing first with `--sector`, `--board`, `--limit`,
or an explicit `--year` range, and always try `--dry-run` on a `--limit`
of a few companies before letting a full run loose.

Options:

| Flag | Meaning |
| --- | --- |
| `--kode-emiten` | One or more tickers/company names, or `all` |
| `--year` | One or more years, ranges (`2020-2026`), or `all` |
| `--periode` | `tw1`, `tw2`, `tw3`, `audit`, or `all` (default) |
| `--report-type` | Default `rdf` (financial statements) |
| `--sector` / `--board` | Server-side filters, only used with `--kode-emiten all` |
| `--limit` | Cap how many companies are processed (smoke-test before a full run) |
| `--output-dir` | Root folder for downloads (default `./data`) |
| `--manifest` | CSV log path (default `<output-dir>/manifest.csv`) |
| `--dry-run` | List what would be downloaded, don't save |
| `--overwrite` | Re-download files that already exist |
| `--max-workers` | Companies processed concurrently (default `1`) |
| `--request-delay` | Seconds between listing requests, per worker (default `0.3`) |
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
published yet simply come back empty and are logged as such (and recorded
as `note=not published` in the manifest).

## The manifest

Every (company, year, period) job appends one row to the manifest CSV:
`timestamp, kode_emiten, year, periode, files_found, files_downloaded,
note`. For a large `--kode-emiten all --year all` run this is what makes
the run resumable and reviewable afterward without re-parsing logs — grep
it for `error:` to find what needs a retry, or diff two runs' manifests to
see what's new.

## Tests

Offline unit tests mock the HTTP layer and check the response-parsing,
company-list-parsing, and year-token-expansion logic without needing
network access:

```bash
pip install pytest
pytest tests/ -v
```

## Known limitation of this dev environment

This scraper was authored and unit-tested in a sandboxed session whose
outbound network access to `idx.co.id` is blocked by policy, so the live
API calls could not be exercised end-to-end here. Run it from a normal
machine/CI with outbound internet access. If IDX has changed a response
shape since, `client.py::_extract_attachments`/`_pick` and
`companies.py::list_companies` are written defensively (multiple key-name
fallbacks, tolerant of missing fields) to reduce the blast radius —
`--dry-run -v --limit 3` is the fastest way to sanity-check a fresh run
before committing to a big one.
