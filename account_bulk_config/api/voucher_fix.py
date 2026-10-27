"""Correct a wrong account or cost center on one submitted document and repost its ledger.

ERPNext lets a few account fields be edited after submit, but not the party account, a Payment
Entry's paid from/to, a Journal Entry's accounts or a POS payment's account. This swaps OLD for NEW
in every Account (or Cost Center) field of the document, header and child tables alike, and
regenerates its GL through Repost Accounting Ledger, with the same closed-period checks as the
bulk ledger update.
"""

import frappe
from frappe import _

from account_bulk_config.api.fields import validate_link
from account_bulk_config.api.ledger_update import _apply_plan, _Blockers, _deferred_invoices

LINK_DOCTYPES = ("Account", "Cost Center")


def _check(voucher_type: str, voucher_no: str, link_doctype: str):
	if link_doctype not in LINK_DOCTYPES:
		frappe.throw(_("Jenis {0} tidak didukung").format(link_doctype))
	if not frappe.has_permission("Repost Accounting Ledger", "create"):
		frappe.throw(
			_("Butuh izin membuat {0} untuk mengoreksi akun dokumen.").format(_("Repost Accounting Ledger")),
			frappe.PermissionError,
		)
	doc = frappe.get_doc(voucher_type, voucher_no)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Hanya dokumen yang sudah submit yang bisa dikoreksi"))
	return doc


def _link_fields(doctype: str, link_doctype: str) -> list[str]:
	return [
		df.fieldname
		for df in frappe.get_meta(doctype).get("fields", {"fieldtype": "Link", "options": link_doctype})
	]


def _locations(doc, link_doctype: str, value: str | None = None) -> list[dict]:
	"""Every (row, field) of the document linking to link_doctype, optionally only those holding value."""
	out = []
	for fieldname in _link_fields(doc.doctype, link_doctype):
		if doc.get(fieldname) and (value is None or doc.get(fieldname) == value):
			out.append(
				{
					"doctype": doc.doctype,
					"rowname": doc.name,
					"field": fieldname,
					"value": doc.get(fieldname),
					"label": _(doc.meta.get_label(fieldname)),
				}
			)
	for table_df in doc.meta.get_table_fields():
		fields = _link_fields(table_df.options, link_doctype)
		if not fields:
			continue
		child_meta = frappe.get_meta(table_df.options)
		for row in doc.get(table_df.fieldname) or []:
			for fieldname in fields:
				if row.get(fieldname) and (value is None or row.get(fieldname) == value):
					out.append(
						{
							"doctype": table_df.options,
							"rowname": row.name,
							"field": fieldname,
							"value": row.get(fieldname),
							"label": _("{0} baris {1}: {2}").format(
								_(table_df.label), row.idx, _(child_meta.get_label(fieldname))
							),
						}
					)
	return out


def _validate_new(doc, link_doctype: str, old: str, new: str | None) -> str | None:
	if not new:
		return _("Nilai baru wajib diisi")
	if new == old:
		return _("Nilai baru sama dengan nilai lama")
	if err := validate_link({"link": link_doctype, "filters": {}}, new, doc.company):
		return err
	if link_doctype == "Account":
		fields = ["account_type", "account_currency", "root_type"]
		old_acc = frappe.db.get_value("Account", old, fields, as_dict=True) or {}
		new_acc = frappe.db.get_value("Account", new, fields, as_dict=True)
		# the ledger keeps party balances and amounts per account: these must line up
		if old_acc.get("account_type") in ("Receivable", "Payable") and (
			new_acc.account_type != old_acc.get("account_type")
		):
			return _("Akun {0} bertipe {1}; penggantinya harus bertipe sama").format(
				old, _(old_acc.get("account_type"))
			)
		if new_acc.account_type in ("Receivable", "Payable") and old_acc.get("account_type") not in (
			"Receivable",
			"Payable",
		):
			return _("Akun {0} adalah akun party ({1}); tidak bisa menggantikan akun biasa").format(
				new, _(new_acc.account_type)
			)
		if old_acc.get("account_currency") and new_acc.account_currency != old_acc.get("account_currency"):
			return _("Mata uang akun berbeda ({0} vs {1})").format(
				old_acc.get("account_currency"), new_acc.account_currency
			)
	return None


def _blocker(doc) -> str | None:
	blockers = _Blockers()
	if reason := blockers.reason(doc.company, doc.doctype, doc.posting_date):
		return reason
	if (doc.doctype, doc.name) in _deferred_invoices([(doc.doctype, doc.name)]):
		return _("Ada deferred revenue/expense, tidak bisa direpost")
	return None


@frappe.whitelist()
def get_values(voucher_type: str, voucher_no: str, link_doctype: str = "Account") -> dict:
	"""Distinct values of the document's Account/Cost Center fields, with where each one is used."""
	doc = _check(voucher_type, voucher_no, link_doctype)
	values = {}
	for loc in _locations(doc, link_doctype):
		values.setdefault(loc["value"], []).append(loc["label"])
	return {
		"company": doc.company,
		"blocked": _blocker(doc),
		"values": [{"value": v, "used_in": labels} for v, labels in values.items()],
	}


@frappe.whitelist()
def preview(
	voucher_type: str, voucher_no: str, old: str, new: str | None = None, link_doctype: str = "Account"
) -> dict:
	"""The fields that would change, or why the document cannot be corrected."""
	doc = _check(voucher_type, voucher_no, link_doctype)
	locations = _locations(doc, link_doctype, old)
	error = _blocker(doc) or (None if locations else _("{0} tidak dipakai di dokumen ini").format(old))
	if not error and new:
		error = _validate_new(doc, link_doctype, old, new)
	warning = None
	if link_doctype == "Account" and frappe.db.get_value("Account", old, "account_type") in (
		"Receivable",
		"Payable",
	):
		warning = _(
			"Akun party: invoice/pembayaran yang dialokasikan ke dokumen ini masih memakai {0}. "
			"Koreksi juga dokumen tersebut agar rekonsiliasi tetap cocok."
		).format(old)
	return {"error": error, "warning": warning, "rows": [loc["label"] for loc in locations]}


@frappe.whitelist(methods=["POST"])
def apply(voucher_type: str, voucher_no: str, old: str, new: str, link_doctype: str = "Account") -> dict:
	"""Swap OLD for NEW on the document and queue its repost."""
	doc = _check(voucher_type, voucher_no, link_doctype)
	locations = _locations(doc, link_doctype, old)
	if err := (
		_blocker(doc)
		or (None if locations else _("{0} tidak dipakai di dokumen ini").format(old))
		or _validate_new(doc, link_doctype, old, new)
	):
		frappe.throw(err)

	change = {
		"name": doc.name,
		"company": doc.company,
		"field": frappe.scrub(link_doctype),
		"old": old,
		"new": new,
	}
	plan = {
		"ready": [
			{
				"voucher_type": doc.doctype,
				"voucher_no": doc.name,
				"posting_date": str(doc.posting_date),
				"rows": [(loc["doctype"], loc["rowname"], loc["field"]) for loc in locations],
				"stock": False,
			}
		],
		"skipped": [],
	}
	result = _apply_plan(change, plan)
	if result["failed"]:
		frappe.throw(result["failed"][0]["reason"])
	return result
