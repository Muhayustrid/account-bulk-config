# Bulk Account Config

Bulk configuration for company default accounts and item defaults.

## Update Jurnal Lama

Setelah akun default diganti (misal Mode of Payment "Tunai" dari *DP Penjualan* ke *Kas Kecil*),
menu **Update Jurnal Lama…** di tiap halaman — atau tawaran yang muncul setelah **Simpan** — mengganti
nilai lama di dokumen yang sudah submit lalu membentuk ulang GL-nya:

- Sales/Purchase Invoice, Payment Entry dan Journal Entry lewat **Repost Accounting Ledger**
  (maks. 50 dokumen per repost, berjalan di background).
- Akun warehouse lewat **Repost Item Valuation** (hanya ledger akuntansi) untuk voucher stok.
- Hanya dokumen yang terkait setting itu yang diubah, misal Mode of Payment hanya dokumen dengan
  mode of payment tersebut; setting Company berlaku untuk semua dokumen company itu.
- Dokumen di periode tertutup (Period Closing Voucher / Accounting Period), dengan deferred
  revenue/expense, atau tipe yang tidak diizinkan di *Accounts Settings > Allowed DocTypes*
  dilewati dan ditampilkan alasannya.
- Butuh izin membuat Repost Accounting Ledger (default: System Manager), atau Repost Item Valuation
  untuk warehouse.
