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
- **Update Account Number / Name** pada akun company induk hanya mengganti akun induk di request itu;
  akun yang sama di semua anak perusahaan diganti nama/nomornya oleh background job (worker queue
  *long* harus jalan), lalu hasilnya muncul sebagai notifikasi. Sebelumnya ERPNext mengganti semuanya
  dalam satu request dan pasti *Request Timed Out* kalau anak perusahaannya banyak.
- Menu **Salin COA ke Anak Perusahaan…** (Chart of Accounts > ⋯, atau Bulk Company Accounts > ⋯)
  membandingkan COA induk dengan anak perusahaan yang dipilih, menampilkan akun yang akan dibuat/
  diupdate/dihapus, lalu menyalinnya. Akun dicocokkan berdasarkan nama dan nomor akun, lalu nama
  saja; akun yang di anak berupa ledger sedangkan di induk berupa grup dilewati.
- Akun yang sudah ada (opsional, default aktif) disamakan Account Type, Freeze, Balance Must Be,
  **induk akunnya** (akun yang dipindah di induk ikut dipindah) dan **nomor akunnya** (akun yang
  diberi/diganti nomor di induk ikut diganti).
- Akun yang hanya ada di anak tidak disentuh, kecuali opsi **Hapus akun di anak yang tidak ada di
  induk** dicentang (untuk akun yang dihapus di induk). Akun yang sudah punya transaksi atau masih
  dipakai sebagai akun default tidak terhapus dan ditampilkan alasannya.
- Tiap akun disimpan sendiri-sendiri: akun yang ditolak ERPNext (misal izin Freeze, saldo tidak
  sesuai Balance Must Be, nomor akun sudah dipakai) dilaporkan, akun lain tetap tersalin.
- Penyalinan lebih dari 30 akun, atau yang mengganti nomor akun, berjalan di background (worker
  queue *long* harus jalan); hasil atau errornya muncul sebagai pesan.
- Pekerjaan background dibagi per 5 anak perusahaan, satu job per batch, berurutan. Progresnya
  muncul sebagai notifikasi "x dari y anak perusahaan selesai". Kalau worker mati di tengah jalan
  (deploy, restart, kehabisan memori), job terjadwal tiap 5 menit melanjutkan batch yang terhenti;
  batch yang tiga kali membuat worker mati dilewati dan dilaporkan. Menjalankan Salin COA lagi aman:
  akun yang sudah tersalin tidak dibuat ulang.
