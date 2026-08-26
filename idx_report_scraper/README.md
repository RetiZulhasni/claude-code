# IDX Financial Report Scraper

Otomatisasi pengunduhan laporan keuangan (PDF) emiten dari
[idx.co.id](https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan)
via API internal yang dipakai halaman tersebut — bukan parsing HTML.

## Cara kerja (pipeline)

1. `fetch_report()` — memanggil endpoint
   `https://idx.co.id/umbraco/Surface/ListedCompany/GetFinancialReport`
   dengan parameter `kodeEmiten`, `year`, `periode` (`tw1`/`tw2`/`tw3`/`tahunan`),
   `reportType=rdf`. Endpoint dan struktur JSON ini bukan API resmi yang
   didokumentasikan IDX — dikonfirmasi dari implementasi scraper publik yang
   sudah berjalan, sehingga sewaktu-waktu bisa berubah tanpa pemberitahuan.
2. `extract_pdf_attachments()` — dari `Results[].Attachments[]`, mengambil
   hanya entri yang berekstensi `.pdf` (laporan lain seperti XBRL diabaikan).
3. `download_pdf()` — mengunduh tiap PDF dengan retry + exponential backoff,
   menghitung SHA-256, menyimpan ke
   `downloads/<KODE_EMITEN>/<TAHUN>/<PERIODE>/<nama_file>.pdf`.
4. `run()` — menjalankan langkah 1-3 untuk semua periode yang diminta, lalu
   menulis `downloads/<KODE_EMITEN>/<TAHUN>/manifest.json` berisi daftar file
   yang berhasil diunduh (nama, URL sumber, path lokal, hash, ukuran, waktu
   unduh) untuk audit/tracking.

Periode yang belum terbit (mis. TW3 tahun berjalan, atau laporan tahunan
sebelum tahun buku ditutup) otomatis dilewati dan dicatat di log, bukan
dianggap error.

## Instalasi

```bash
cd idx_report_scraper
pip install -r requirements.txt
```

## Pemakaian

```bash
# Berdasarkan nama perusahaan (harus terdaftar di companies.py)
python -m idx_report_scraper.cli \
  --company "PT Adaro Andalan Indonesia Tbk" \
  --year 2026

# Atau langsung pakai kode ticker
python -m idx_report_scraper.cli --kode-emiten AADI --year 2026

# Batasi ke periode tertentu
python -m idx_report_scraper.cli --kode-emiten AADI --year 2026 --periode tw1 tw2

# Ubah folder tujuan
python -m idx_report_scraper.cli --kode-emiten AADI --year 2026 --out-dir /path/ke/folder
```

Menambahkan perusahaan baru cukup dengan menambah entri di
`KNOWN_COMPANIES` pada `companies.py`, atau langsung memakai `--kode-emiten`
tanpa mengubah kode.

## Catatan penting

- **idx.co.id memblokir request tanpa identitas browser** — client di sini
  sudah mengirim `User-Agent`/`Referer` yang wajar, tapi situs bisa saja
  menambah proteksi (captcha, rate limit) sewaktu-waktu.
- **Sandbox pengembangan ini tidak punya akses keluar ke idx.co.id**
  (diblokir oleh egress proxy lingkungan), sehingga scraper ini divalidasi
  dengan unit test offline (`tests/test_downloader.py`, mem-mock response
  API) dan bukan dengan menjalankannya langsung ke situs IDX. Jalankan dari
  mesin/lingkungan yang punya akses internet normal ke idx.co.id.
- Untuk tahun berjalan (mis. 2026 saat skrip ini dibuat), laporan tahunan
  (`tahunan`) baru terbit tahun berikutnya, dan TW3 baru terbit sekitar
  Oktober/November — jangan kaget kalau periode tersebut belum menghasilkan
  file apa pun.

## Testing

```bash
python -m unittest idx_report_scraper.tests.test_downloader -v
```

Test ini berjalan sepenuhnya offline (API di-mock) dan memverifikasi:
resolusi nama perusahaan ke kode ticker, filter lampiran PDF, serta alur
unduh + penulisan manifest.
