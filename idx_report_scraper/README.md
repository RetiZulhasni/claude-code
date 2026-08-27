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
4. `metadata.extract_entity_metadata()` — begitu satu PDF selesai diunduh,
   modul ini membaca file lokal yang sudah tersimpan (tanpa request ulang)
   dan mengambil "Nama Entitas"/"Kode Entitas" dari halaman sampul laporan
   — dicoba dulu sebagai tabel, baru fallback ke pencarian teks untuk
   template PDF yang tidak menyajikannya sebagai tabel.
5. `run()` — menjalankan langkah 1-4 untuk semua periode yang diminta, lalu
   menulis `downloads/<KODE_EMITEN>/<TAHUN>/manifest.json` berisi daftar file
   yang berhasil diunduh (nama, URL sumber, path lokal, hash, ukuran, waktu
   unduh, nama & kode entitas) untuk audit/tracking.

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

- **idx.co.id ada di belakang Cloudflare**, yang menolak request dari
  library `requests` biasa (403 "Attention Required") berdasarkan
  fingerprint TLS-nya — bukan cuma dari header `User-Agent`/`Referer`.
  Karena itu client di sini pakai
  [`curl_cffi`](https://github.com/lexiforest/curl_cffi) dengan
  `impersonate="chrome"`, yang meniru fingerprint TLS Chrome asli;
  API-nya sengaja dibuat mirip `requests` (`Session`, `.json()`,
  `.iter_content()`) supaya kode pipeline-nya tidak berubah banyak. Situs
  tetap bisa saja menambah proteksi lain (captcha, rate limit, Bot Fight
  Mode yang lebih ketat) sewaktu-waktu.
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
python -m unittest discover -s idx_report_scraper/tests -p "test_*.py" -v
```

Test ini berjalan sepenuhnya offline (API dan parsing PDF di-mock) dan
memverifikasi: resolusi nama perusahaan ke kode ticker, filter lampiran PDF,
alur unduh + penulisan manifest, serta ekstraksi nama/kode entitas dari
halaman sampul laporan (baik lewat tabel maupun fallback teks).
