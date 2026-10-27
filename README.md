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

## Koreksi Akun per Dokumen

Kalau satu dokumen yang sudah submit ternyata salah akun atau cost center, buka dokumennya
(Sales/Purchase Invoice, Payment Entry, Journal Entry, Purchase Receipt), lalu pilih
**Actions > Koreksi Akun**. Pilih nilai yang keliru (daftar diambil dari akun yang dipakai dokumen itu)
dan penggantinya, cek preview field yang akan berubah, lalu **Terapkan & Repost**.

- Semua field Account / Cost Center yang berisi nilai lama diganti, termasuk yang tidak bisa diedit
  lewat *Update After Submit* ERPNext (akun piutang/utang, paid from/to, akun Journal Entry,
  akun pembayaran POS).
- Akun piutang/utang hanya bisa diganti dengan akun bertipe sama, dan mata uang akun harus sama.
- Aturan periode tertutup, deferred dan izin sama dengan **Update Jurnal Lama**.

## Salin COA ke Anak Perusahaan

ERPNext menyalin akun baru dari company induk teratas ke **setiap** anak perusahaan dalam satu
request simpan, dan menolak simpan kalau induk akun itu belum ada di salah satu anak. Kalau anak
perusahaannya banyak, request ini bisa melewati batas waktu web (*Request Timed Out*). App ini mengubahnya:

- Akun yang disimpan di company induk langsung tersimpan. Salinan ke anak perusahaan dibuat oleh
  background job (worker harus jalan), termasuk induk akunnya kalau belum ada. Hasilnya muncul
  sebagai notifikasi; akun yang tidak bisa disalin ditampilkan alasannya.
- Menu **Salin COA ke Anak Perusahaan…** (Chart of Accounts > ⋯, atau Bulk Company Accounts > ⋯)
  membandingkan COA induk dengan anak perusahaan yang dipilih, menampilkan akun yang akan dibuat/
  diupdate, lalu menyalinnya. Akun dicocokkan berdasarkan nama (dan nomor akun bila ada); akun yang
  sudah ada disamakan Account Type, Freeze dan Balance Must Be-nya (opsional); akun yang hanya ada
  di anak tidak disentuh; akun yang di anak berupa ledger sedangkan di induk berupa grup dilewati.
- Penyalinan lebih dari 30 akun berjalan di background.
