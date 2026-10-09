# Status proyek: IDX Financial Report Scraper + Account Intelligence

Dokumen ini dibuat agar percakapan Claude baru bisa langsung melanjutkan
tanpa kehilangan konteks. Jika memulai obrolan baru, lampirkan/rujuk file
ini (path: `idx_report_scraper/STATUS.md` di branch
`claude/idx-financial-report-scraper-xrd6z6`).

## Tujuan proyek

Kumparan (media) ingin menilai emiten IDX mana yang potensial jadi klien
(business development), berdasarkan kesehatan keuangan dari laporan
keuangan resmi (PDF) yang dipublikasikan di idx.co.id. Proyek ini
mengotomasi: (1) unduh PDF laporan keuangan per emiten/tahun/periode, dan
(2) ekstrak angka-angka kunci + susun workbook Excel analisis kesehatan.

## Yang sudah selesai & teruji

1. **Scraper inti** (`downloader.py`, `bulk.py`, `companies.py`,
   `metadata.py`) — unduh PDF per emiten/tahun/periode (tw1/tw2/tw3/tahunan)
   dari API internal idx.co.id, dengan fallback tebak-URL (`--direct`) saat
   API tidak stabil, pakai `curl_cffi` (impersonate Chrome) untuk
   melewati proteksi Cloudflare. Mendukung satu emiten atau banyak
   (`--tickers-file`) dengan checkpoint resumable (`progress.json`).
2. **Ekstraksi finansial** (`financials.py`) — parsing badan laporan XBRL
   (bukan cuma sampul): sektor/subsektor/industri, Pendapatan, Laba
   Bersih, Beban Penjualan/Administrasi, Kas, Total Aset, Aset Lancar,
   Liabilitas Jangka Pendek, Jumlah Liabilitas, Jumlah Ekuitas. Sudah
   divalidasi byte-per-byte terhadap 2 PDF AALI asli (tahunan audited +
   TW1 unaudited) — total aset = liabilitas + ekuitas, cocok persis.
3. **Workbook otomatis** (`intelligence.py`, CLI `--build-intelligence`) —
   baca ulang PDF yang sudah terunduh (tanpa network lagi), hasilkan
   3 sheet:
   - **Profil & Keuangan**: 1 baris per emiten, termasuk 4 rasio kesehatan
     sebagai rumus Excel aktif — **Current Ratio**, **DER**, **Margin
     Laba Bersih**, **ROE**.
   - **Matriks Kesehatan**: tabel referensi 16 kombinasi
     Revenue×Profit×Karyawan×Cash → kategori, disalin dari template
     referensi tim.
   - **Kalkulator Kesehatan**: rumus `INDEX`/`MATCH` otomatis, ambang
     B/K/Byk/Sdk bisa diedit manual di sel biru (nilainya diwarisi dari
     template referensi tim, bukan standar baku).
4. Semua diuji: 39 unit test offline (mock PDF), ditambah validasi manual
   terhadap PDF AALI asli dan `recalc.py` (LibreOffice) untuk memastikan
   rumus Excel tidak error.
5. Commit terakhir di GitHub: `4f090c4` — *"Add balance-sheet-derived
   health ratios (Current Ratio, DER, margin, ROE)"* di branch
   **`claude/idx-financial-report-scraper-xrd6z6`** — sudah terkonfirmasi
   tersimpan & cocok dengan kode yang diuji.

## Batasan yang disadari (bukan bug, scope keputusan)

- **Karyawan (jumlah pegawai)** sengaja dikosongkan di Kalkulator
  Kesehatan — tidak ada di laporan keuangan XBRL, harus diisi manual.
- **Bagian kualitatif** (kalender momen/HUT/RUPST, nama direksi, narasi
  komunikasi, pemetaan produk Kumparan, estimasi revenue deal) **belum
  dan tidak akan** diotomasi dari kode ini — disepakati di awal proyek
  sebagai proses riset manual/AI-assisted per perusahaan, bukan sesuatu
  yang bisa diturunkan dari PDF laporan keuangan.
- **Validasi ekstraksi** baru dilakukan penuh untuk AALI (2 PDF, format
  berbeda: tahunan & kuartalan). Format XBRL IDX terstandarisasi OJK
  sehingga seharusnya generalisasi ke emiten lain, tapi belum diverifikasi
  langsung untuk emiten lain selain AALI.
- Ambang "Besar/Kecil" di Kalkulator Kesehatan (Revenue≥Rp10rb miliar,
  Profit≥Rp1rb miliar, Karyawan≥5000, Cash≥Rp1rb miliar) adalah warisan
  dari template referensi tim, bukan standar industri/regulasi resmi —
  tidak ada standar pemerintah Indonesia yang pas untuk membedakan
  besar/kecil di antara emiten IDX yang sudah mapan (PP UMKM & POJK skala
  kecil/menengah dirancang untuk perusahaan jauh lebih kecil).

## Rencana lanjutan (belum dikerjakan, belum diminta eksplisit)

1. Jalankan `--tickers-file` untuk bulk-download seluruh ~962 emiten IDX
   (daftar ticker sudah ada: `List_perusahaan_IDX__20260827.csv`), lalu
   `--build-intelligence` satu kali untuk seluruh batch.
2. Opsional: tambah rasio **Arus Kas Operasi (CFO) vs Laba Bersih**
   (kualitas laba) — butuh parsing section Laporan Arus Kas yang belum
   disentuh `financials.py` (effort lebih besar dari 4 rasio yang sudah
   ada, karena section ini beda struktur).
3. Opsional: screening otomatis berbasis persentil (bukan ambang absolut)
   dari 962 emiten, sebagai alternatif ambang B/K yang lebih "berbasis
   data" ketimbang warisan template.
4. Lapisan kualitatif (event calendar, direksi, narasi, product mapping,
   estimasi revenue) tetap manual/AI-assisted per batch emiten hasil
   screening — bukan tugas kode ini.

## Cara melanjutkan di komputer/obrolan baru

```bash
git clone <repo-url>
cd claude-code
git checkout claude/idx-financial-report-scraper-xrd6z6
cd idx_report_scraper && pip install -r requirements.txt && cd ..
python3 -m idx_report_scraper.cli --kode-emiten AALI --year 2026 --direct   # contoh unduh
python3 -m idx_report_scraper.cli --build-intelligence --year 2026 --intelligence-output Account_Intelligence.xlsx
```

Konteks bisnis (B2B media/revenue Kumparan), file referensi (template
Account Intelligence 12-sheet, katalog 125 produk Kumparan, daftar 962
ticker IDX) ada di riwayat percakapan sebelumnya — kalau mulai obrolan
baru dan file-file itu dibutuhkan lagi, unggah ulang karena tidak
tersimpan di repo ini.
