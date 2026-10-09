import unittest

from idx_report_scraper.financials import FinancialProfile
from idx_report_scraper.validation import check_profile


class CheckProfileTests(unittest.TestCase):
    def test_consistent_profile_passes_every_check(self):
        p = FinancialProfile(
            pendapatan=1000.0, beban_pokok_penjualan=-600.0, laba_bruto=400.0,
            jumlah_aset=500.0, jumlah_aset_lancar=200.0,
            jumlah_liabilitas=300.0, jumlah_liabilitas_jangka_pendek=100.0, jumlah_ekuitas=200.0,
        )
        self.assertEqual(set(check_profile(p).values()), {"OK"})

    def test_balance_sheet_mismatch_fails(self):
        p = FinancialProfile(jumlah_aset=500.0, jumlah_liabilitas=300.0, jumlah_ekuitas=150.0)
        self.assertEqual(check_profile(p)["aset=liab+ekuitas"], "GAGAL")

    def test_missing_fields_are_not_applicable(self):
        # e.g. a bank: no current/non-current split, no cost of revenue line
        p = FinancialProfile(jumlah_aset=500.0, jumlah_liabilitas=300.0, jumlah_ekuitas=200.0)
        results = check_profile(p)
        self.assertEqual(results["aset=liab+ekuitas"], "OK")
        self.assertEqual(results["aset_lancar<=aset"], "N/A")
        self.assertEqual(results["laba_bruto=pendapatan-bpp"], "N/A")


if __name__ == "__main__":
    unittest.main()
