# IDX Financial Report Scraper

Otomatisasi pengunduhan laporan keuangan (PDF) emiten dari
[idx.co.id](https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan)
via API internal yang dipakai halaman tersebut — bukan parsing HTML.

## Cara kerja (pipeline)

1. `fetch_report()` — memanggil endpoint
   `https://www.idx.co.id/umbraco/Surface/ListedCompany/GetFinancialReport`
   dengan parameter `kodeEmiten`, `year`, `periode` (`tw1`/`tw2`/`tw3`/`tahunan`),
   `reportType=rdf`. Endpoint dan struktur JSON ini bukan API resmi yang
   didokumentasikan IDX, jadi sewaktu-waktu bisa berubah tanpa pemberitahuan
   — kalau endpoint ini mengembalikan 404 (bukan hasil kosong untuk periode
   yang memang belum terbit), `run()` otomatis jatuh ke
   `guess_pdf_attachment()`: menebak URL PDF standar langsung berdasarkan
   pola penamaan file IDX yang sudah diverifikasi manual
   (`.../Laporan Keuangan Tahun <tahun>/<TWn>/<KODE>/FinancialStatement-<tahun>-<romawi>-<KODE>.pdf`).
   Fallback ini best-effort: hanya menangkap satu nama file standar, jadi
   varian PDF lain (mis. salinan berlabel nama perusahaan) yang cuma
   tercantum di JSON API bisa terlewat.
2. `extract_pdf_attachments()` — dari (bare array, bukan `{"Results": [...]}`)
   respons API, mengambil hanya entri berekstensi `.pdf` (laporan lain
   seperti XBRL/XLSX diabaikan) dan menyertakan `NamaEmiten`/`KodeEmiten`
   dari level induknya sebagai `_entity_name`/`_entity_code`.
3. `download_pdf()` — mengunduh tiap PDF dengan retry + exponential backoff,
   menghitung SHA-256, menyimpan ke
   `downloads/<TAHUN>/<KODE_EMITEN>/<PERIODE>/<nama_file>.pdf`.
4. `metadata.extract_entity_metadata()` — fallback kalau API tidak
   menyertakan `NamaEmiten`/`KodeEmiten` (mis. lewat jalur tebakan URL):
   membaca file PDF lokal yang sudah tersimpan (tanpa request ulang) dan
   mengambil "Nama Entitas"/"Kode Entitas" dari halaman sampul laporan —
   dicoba dulu sebagai tabel, baru fallback ke pencarian teks.
5. `run()` — menjalankan langkah 1-4 untuk semua periode yang diminta, lalu
   menulis `downloads/<TAHUN>/<KODE_EMITEN>/manifest.json` berisi daftar file
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

# Banyak emiten sekaligus (mis. semua perusahaan tercatat), dengan resume otomatis
python -m idx_report_scraper.cli --tickers-file tickers.txt --year 2026

# Lewati endpoint API yang tidak stabil, langsung pakai pola URL PDF yang sudah diverifikasi
python -m idx_report_scraper.cli --kode-emiten AADI --year 2026 --direct
```

Menambahkan perusahaan baru cukup dengan menambah entri di
`KNOWN_COMPANIES` pada `companies.py`, atau langsung memakai `--kode-emiten`
tanpa mengubah kode.

### `--direct`: lewati endpoint API sepenuhnya

Endpoint `GetFinancialReport` kadang membalas 404, kadang 403 (kemungkinan
rate-limit/proteksi Cloudflare), padahal pola URL PDF statis yang
ditebaknya (`guess_pdf_attachment()`) sudah diverifikasi cocok
byte-per-byte untuk TW1/TW2/TW3/Tahunan. `--direct` melewati panggilan API
itu sama sekali (termasuk warm-up sesi) dan langsung memakai pola URL
tersebut untuk semua periode yang diminta - lebih stabil untuk run
berskala besar, dengan trade-off yang sama seperti fallback-nya: hanya
menemukan satu nama file PDF standar, varian lain (mis. salinan berlabel
nama perusahaan) yang cuma tercantum di JSON API akan terlewat.

## Mengunduh banyak emiten sekaligus (`--tickers-file`)

`--tickers-file` memproses satu file berisi banyak kode ticker (satu per
baris, atau kolom `kode`/`code`/`ticker` kalau filenya `.csv`) secara
berurutan, dengan jeda `--delay` detik antar-emiten (default 1 detik, agar
tidak membebani idx.co.id). Setiap emiten yang selesai — sukses maupun
gagal — langsung dicatat ke `<out-dir>/progress.json`.

**Resume otomatis:** kalau proses terhenti di tengah jalan (crash, error,
koneksi putus, atau `Ctrl-C`), jalankan perintah yang **persis sama** lagi.
Emiten yang sudah `"status": "done"` di `progress.json` otomatis dilewati,
dan proses lanjut dari emiten yang belum selesai atau yang gagal
sebelumnya. Pakai `--no-resume` untuk memaksa proses ulang semua emiten
dari awal.

```bash
python -m idx_report_scraper.cli --tickers-file tickers.txt --year 2026 --delay 2
# terhenti di tengah jalan? jalankan lagi persis sama - otomatis lanjut:
python -m idx_report_scraper.cli --tickers-file tickers.txt --year 2026 --delay 2
```

**Mendapatkan daftar kode ticker semua emiten:** repo ini belum
menyertakan cara otomatis untuk menarik daftar seluruh ~900+ perusahaan
tercatat dari idx.co.id (endpoint-nya belum diverifikasi, berbeda dari
endpoint `GetFinancialReport`). Untuk sekarang, siapkan `tickers.txt`
secara manual, misalnya dari unduhan "Daftar Perusahaan Tercatat"
(Excel/CSV) yang biasanya tersedia di halaman profil perusahaan tercatat
IDX, atau dari sumber data pasar modal lain yang sudah Anda punya.

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
alur unduh + penulisan manifest, ekstraksi nama/kode entitas dari halaman
sampul laporan (baik lewat tabel maupun fallback teks), serta orkestrasi
banyak-emiten (`bulk.py`) termasuk resume dari checkpoint.
