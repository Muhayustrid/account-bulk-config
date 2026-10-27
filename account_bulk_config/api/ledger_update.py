"""Carry a changed default over to submitted documents and repost their ledgers.

When a setting changes from OLD to NEW (e.g. a Mode of Payment's default account from
"DP Penjualan" to "Kas Kecil"), the documents already submitted with OLD keep posting to it.
This module finds those documents, swaps OLD for NEW in the fields the setting fills, and
regenerates their GL through ERPNext's own repost doctypes:

- Repost Accounting Ledger for invoices, payments and journals (the documents it supports),
- Repost Item Valuation (accounting ledgers only) for stock vouchers when a warehouse's
  account changes, since their GL is derived from the warehouse account, not a document field.

Vouchers in a closed period (Period Closing Voucher or a closed Accounting Period), with
deferred revenue/expense, or of a type not allowed to be reposted are left alone and reported.
"""

import json
import uuid

import frappe
from frappe import _
from frappe.utils import getdate

from account_bulk_config.api.batch import CHILD_DOCTYPES, TARGETS
from account_bulk_config.api.fields import validate_link

# Repost Accounting Ledger refuses more vouchers than this in one document
REPOST_CHUNK = 50
# above this many vouchers the update runs in a background job
SYNC_LIMIT = 100

NAME = "$name"

# Where a setting's value lands on submitted documents. Each location is one of:
#   {"voucher_type", "table" (child doctype or None for the header), "field",
#    "filters" (on the row), "parent_filters" (on the voucher)}  -> field swapped, then reposted
#   {"kind": "gl"}    -> no document field holds it (picked at posting time): repost vouchers whose
#                        GL uses OLD so they pick up NEW from the setting
#   {"kind": "stock"} -> stock vouchers of the warehouse whose GL uses OLD, via Repost Item Valuation
# "$name" in a filter stands for the changed document (Mode of Payment, POS Profile, Item, ...).


def _loc(voucher_type, field, table=None, filters=None, parent_filters=None):
	return {
		"voucher_type": voucher_type,
		"table": table,
		"field": field,
		"filters": filters or {},
		"parent_filters": parent_filters or {},
	}


_CASH_BANK = [
	_loc("Payment Entry", "paid_from"),
	_loc("Payment Entry", "paid_to"),
	_loc("Journal Entry", "account", "Journal Entry Account"),
	_loc("Sales Invoice", "account", "Sales Invoice Payment"),
	_loc("Sales Invoice", "cash_bank_account"),
	_loc("Sales Invoice", "account_for_change_amount"),
	_loc("Purchase Invoice", "cash_bank_account"),
]


def _party_account(party_type, invoice_type, invoice_field):
	return [
		_loc(invoice_type, invoice_field),
		_loc("Payment Entry", "paid_from", parent_filters={"party_type": party_type}),
		_loc("Payment Entry", "paid_to", parent_filters={"party_type": party_type}),
		_loc("Journal Entry", "account", "Journal Entry Account", filters={"party_type": party_type}),
	]


def _item_rules(row_filter):
	"""Item and Item Group defaults: the invoice item rows of that item / item group."""
	f = {row_filter: NAME}
	return {
		"income_account": [_loc("Sales Invoice", "income_account", "Sales Invoice Item", f)],
		"expense_account": [
			_loc("Sales Invoice", "expense_account", "Sales Invoice Item", f),
			_loc("Purchase Invoice", "expense_account", "Purchase Invoice Item", f),
		],
		"selling_cost_center": [_loc("Sales Invoice", "cost_center", "Sales Invoice Item", f)],
		"buying_cost_center": [_loc("Purchase Invoice", "cost_center", "Purchase Invoice Item", f)],
		"default_discount_account": [_loc("Sales Invoice", "discount_account", "Sales Invoice Item", f)],
	}


_POS = {"pos_profile": NAME}

RULES = {
	"company": {
		"default_cash_account": _CASH_BANK,
		"default_bank_account": _CASH_BANK,
		"default_receivable_account": _party_account("Customer", "Sales Invoice", "debit_to"),
		"default_payable_account": _party_account("Supplier", "Purchase Invoice", "credit_to"),
		"default_income_account": [_loc("Sales Invoice", "income_account", "Sales Invoice Item")],
		"default_expense_account": [
			_loc("Sales Invoice", "expense_account", "Sales Invoice Item"),
			_loc("Purchase Invoice", "expense_account", "Purchase Invoice Item"),
		],
		"write_off_account": [
			_loc("Sales Invoice", "write_off_account"),
			_loc("Purchase Invoice", "write_off_account"),
		],
		"cost_center": [
			_loc("Sales Invoice", "cost_center"),
			_loc("Sales Invoice", "cost_center", "Sales Invoice Item"),
			_loc("Purchase Invoice", "cost_center"),
			_loc("Purchase Invoice", "cost_center", "Purchase Invoice Item"),
			_loc("Payment Entry", "cost_center"),
			_loc("Journal Entry", "cost_center", "Journal Entry Account"),
		],
		# taken from the company when the GL is built, so a repost alone moves them
		"round_off_account": [{"kind": "gl"}],
		"exchange_gain_loss_account": [{"kind": "gl"}],
	},
	"mode_of_payment": {
		"default_account": [
			_loc("Sales Invoice", "account", "Sales Invoice Payment", {"mode_of_payment": NAME}),
			_loc(
				"Payment Entry",
				"paid_to",
				parent_filters={"mode_of_payment": NAME, "payment_type": "Receive"},
			),
			_loc(
				"Payment Entry",
				"paid_from",
				parent_filters={"mode_of_payment": NAME, "payment_type": "Pay"},
			),
			_loc("Purchase Invoice", "cash_bank_account", parent_filters={"mode_of_payment": NAME}),
			_loc(
				"Journal Entry", "account", "Journal Entry Account", parent_filters={"mode_of_payment": NAME}
			),
		],
	},
	"pos_profile": {
		"income_account": [
			_loc("Sales Invoice", "income_account", "Sales Invoice Item", parent_filters=_POS)
		],
		"expense_account": [
			_loc("Sales Invoice", "expense_account", "Sales Invoice Item", parent_filters=_POS)
		],
		"cost_center": [
			_loc("Sales Invoice", "cost_center", parent_filters=_POS),
			_loc("Sales Invoice", "cost_center", "Sales Invoice Item", parent_filters=_POS),
		],
		"account_for_change_amount": [
			_loc("Sales Invoice", "account_for_change_amount", parent_filters=_POS)
		],
		"write_off_account": [_loc("Sales Invoice", "write_off_account", parent_filters=_POS)],
		"write_off_cost_center": [_loc("Sales Invoice", "write_off_cost_center", parent_filters=_POS)],
	},
	"item": _item_rules("item_code"),
	"item_group": _item_rules("item_group"),
	"warehouse": {"account": [{"kind": "stock"}]},
}

# Repost Accounting Ledger handles these itself (erpnext's repost_allowed_doctypes hook)
GL_VOUCHER_TYPES = ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Purchase Receipt")


@frappe.whitelist()
def get_supported_fields(target: str) -> list[str]:
	"""Fieldnames of the target whose change can be carried over to submitted documents."""
	return list(RULES.get(target, {}))


@frappe.whitelist()
def get_current_value(target: str, name: str, company: str, field: str) -> str | None:
	"""What the setting holds now for (name, company), to prefill the new value."""
	if field not in RULES.get(target, {}):
		return None
	doctype, child_table_field, _fields = TARGETS[target]
	if not frappe.has_permission(doctype, "read", doc=name):
		return None
	if not child_table_field:
		return frappe.db.get_value(doctype, name, field)
	return frappe.db.get_value(
		CHILD_DOCTYPES[target],
		{"parenttype": doctype, "parent": name, "company": company},
		field,
	)


def _check_permission(target: str) -> None:
	doctype = "Repost Item Valuation" if target == "warehouse" else "Repost Accounting Ledger"
	if not frappe.has_permission(doctype, "create"):
		frappe.throw(
			_("Butuh izin membuat {0} untuk mengubah jurnal yang sudah terbentuk.").format(_(doctype)),
			frappe.PermissionError,
		)


def _parse(changes) -> list[dict]:
	if isinstance(changes, str):
		changes = json.loads(changes)
	return [
		c
		for c in changes or []
		if (c.get("old") or None) and (c.get("old") or None) != (c.get("new") or None)
	]


def _resolve(filters: dict, name: str) -> dict:
	return {k: (name if v == NAME else v) for k, v in filters.items()}


def _date_filter(from_date, to_date):
	if from_date and to_date:
		return ["between", [from_date, to_date]]
	if from_date:
		return [">=", from_date]
	if to_date:
		return ["<=", to_date]
	return None


def _vouchers_with_field(loc, change, from_date, to_date) -> dict:
	"""{voucher_no: {"posting_date", "rows": [(doctype, rowname)]}} where loc's field holds OLD."""
	vtype, table, field = loc["voucher_type"], loc["table"], loc["field"]
	name, company, old = change["name"], change["company"], change["old"]

	parent_filters = {"docstatus": 1, "company": company, **_resolve(loc["parent_filters"], name)}
	if date_filter := _date_filter(from_date, to_date):
		parent_filters["posting_date"] = date_filter

	found = {}
	if not table:
		for v in frappe.get_all(
			vtype, filters={**parent_filters, field: old}, fields=["name", "posting_date"]
		):
			found[v.name] = {"posting_date": v.posting_date, "rows": [(vtype, v.name)]}
		return found

	rows = frappe.get_all(
		table,
		filters={"parenttype": vtype, "docstatus": 1, field: old, **_resolve(loc["filters"], name)},
		fields=["name", "parent"],
	)
	if not rows:
		return found
	parents = {
		v.name: v.posting_date
		for v in frappe.get_all(
			vtype,
			filters={**parent_filters, "name": ["in", list({r.parent for r in rows})]},
			fields=["name", "posting_date"],
		)
	}
	for r in rows:
		if r.parent in parents:
			found.setdefault(r.parent, {"posting_date": parents[r.parent], "rows": []})["rows"].append(
				(table, r.name)
			)
	return found


def _vouchers_by_gl(change, from_date, to_date) -> dict:
	"""{(voucher_type, voucher_no): posting_date} whose live GL uses OLD."""
	filters = {
		"company": change["company"],
		"account": change["old"],
		"is_cancelled": 0,
		"voucher_type": ["in", list(GL_VOUCHER_TYPES)],
	}
	if date_filter := _date_filter(from_date, to_date):
		filters["posting_date"] = date_filter
	return {
		(g.voucher_type, g.voucher_no): g.posting_date
		for g in frappe.get_all(
			"GL Entry",
			filters=filters,
			fields=["voucher_type", "voucher_no", "posting_date"],
			distinct=True,
		)
	}


def _stock_vouchers(change, from_date, to_date) -> dict:
	"""{(voucher_type, voucher_no): (posting_date, posting_time)} of the warehouse posting to OLD."""
	filters = {"warehouse": change["name"], "is_cancelled": 0, "company": change["company"]}
	if date_filter := _date_filter(from_date, to_date):
		filters["posting_date"] = date_filter
	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters=filters,
		fields=["voucher_type", "voucher_no", "posting_date", "posting_time"],
		distinct=True,
	)
	by_voucher = {(s.voucher_type, s.voucher_no): (s.posting_date, s.posting_time) for s in sles}
	if not by_voucher:
		return {}
	with_old = {
		(g.voucher_type, g.voucher_no)
		for g in frappe.get_all(
			"GL Entry",
			filters={
				"company": change["company"],
				"account": change["old"],
				"is_cancelled": 0,
				"voucher_no": ["in", list({v[1] for v in by_voucher})],
			},
			fields=["voucher_type", "voucher_no"],
			distinct=True,
		)
	}
	return {k: v for k, v in by_voucher.items() if k in with_old}


class _Blockers:
	"""Why a voucher of a company cannot be reposted, cached per company."""

	def __init__(self):
		self._pcv = {}
		self._periods = {}
		self._allowed = None
		self._roles = set(frappe.get_roles())

	def allowed_types(self) -> set:
		if self._allowed is None:
			self._allowed = set(frappe.get_all("Repost Allowed Types", pluck="document_type", distinct=True))
		return self._allowed

	def last_closing(self, company):
		if company not in self._pcv:
			dates = frappe.get_all(
				"Period Closing Voucher",
				filters={"company": company, "docstatus": 1},
				order_by="period_end_date desc",
				pluck="period_end_date",
				limit=1,
			)
			self._pcv[company] = getdate(dates[0]) if dates else None
		return self._pcv[company]

	def closed_periods(self, company):
		if company not in self._periods:
			ap = frappe.qb.DocType("Accounting Period")
			cd = frappe.qb.DocType("Closed Document")
			self._periods[company] = (
				frappe.qb.from_(ap)
				.join(cd)
				.on(cd.parent == ap.name)
				.select(ap.name, ap.start_date, ap.end_date, ap.exempted_role, cd.document_type)
				.where((ap.company == company) & (ap.disabled == 0) & (cd.closed == 1))
				.run(as_dict=True)
			)
		return self._periods[company]

	def reason(self, company, voucher_type, posting_date, needs_repost_type=True) -> str | None:
		if needs_repost_type and voucher_type not in self.allowed_types():
			return _("{0} tidak diizinkan direpost (Accounts Settings > Allowed DocTypes)").format(
				_(voucher_type)
			)
		posting_date = getdate(posting_date)
		closing = self.last_closing(company)
		if closing and posting_date <= closing:
			return _("Periode sudah ditutup (Period Closing Voucher s.d. {0})").format(
				frappe.format(closing, "Date")
			)
		for p in self.closed_periods(company):
			if (
				p.document_type == voucher_type
				and getdate(p.start_date) <= posting_date <= getdate(p.end_date)
				and not (p.exempted_role and p.exempted_role in self._roles)
			):
				return _("Accounting Period {0} ditutup untuk {1}").format(p.name, _(voucher_type))
		return None


def _deferred_invoices(vouchers) -> set:
	"""Invoices with deferred revenue/expense rows; Repost Accounting Ledger refuses them."""
	out = set()
	for vtype, table, flag in (
		("Sales Invoice", "Sales Invoice Item", "enable_deferred_revenue"),
		("Purchase Invoice", "Purchase Invoice Item", "enable_deferred_expense"),
	):
		names = [v for t, v in vouchers if t == vtype]
		if names:
			out.update(
				(vtype, p)
				for p in frappe.get_all(
					table, filters={"parent": ["in", names], flag: 1}, pluck="parent", distinct=True
				)
			)
	return out


def _plan_change(target, change, from_date, to_date, blockers) -> dict:
	"""Vouchers to update for one change, and the ones skipped with their reason."""
	locations = RULES.get(target, {}).get(change["field"]) or []
	vouchers = {}  # (voucher_type, voucher_no) -> {"posting_date", "rows", ...}

	for loc in locations:
		kind = loc.get("kind")
		if kind == "gl":
			for key, posting_date in _vouchers_by_gl(change, from_date, to_date).items():
				vouchers.setdefault(key, {"posting_date": posting_date, "rows": []})
		elif kind == "stock":
			for key, (posting_date, posting_time) in _stock_vouchers(change, from_date, to_date).items():
				vouchers.setdefault(
					key,
					{"posting_date": posting_date, "posting_time": posting_time, "rows": [], "stock": True},
				)
		else:
			for vno, info in _vouchers_with_field(loc, change, from_date, to_date).items():
				entry = vouchers.setdefault(
					(loc["voucher_type"], vno), {"posting_date": info["posting_date"], "rows": []}
				)
				entry["rows"].extend((dt, rn, loc["field"]) for dt, rn in info["rows"])

	deferred = _deferred_invoices(list(vouchers))
	ready, skipped = [], []
	for (vtype, vno), info in sorted(vouchers.items(), key=lambda kv: (str(kv[1]["posting_date"]), kv[0])):
		stock = info.get("stock")
		reason = blockers.reason(change["company"], vtype, info["posting_date"], needs_repost_type=not stock)
		if not reason and (vtype, vno) in deferred:
			reason = _("Ada deferred revenue/expense, tidak bisa direpost")
		item = {"voucher_type": vtype, "voucher_no": vno, "posting_date": str(info["posting_date"])}
		if reason:
			skipped.append({**item, "reason": reason})
		else:
			ready.append(
				{**item, "rows": info["rows"], "stock": bool(stock), "posting_time": info.get("posting_time")}
			)
	return {"ready": ready, "skipped": skipped}


def _validate_change(target, change) -> str | None:
	if change.get("field") not in RULES.get(target, {}):
		return _("Field {0} tidak didukung untuk update jurnal").format(change.get("field"))
	if not change.get("company"):
		return _("Company wajib diisi")
	if not change.get("new"):
		return _("Nilai baru wajib diisi")
	field_def = next(f for f in TARGETS[target][2] if f["fieldname"] == change["field"])
	if not frappe.db.exists(field_def["link"], change["old"]):
		return _("{0} {1} tidak ditemukan").format(_(field_def["link"]), change["old"])
	if err := validate_link(field_def, change["new"], change["company"]):
		return err
	if any(loc.get("kind") for loc in RULES[target][change["field"]]):
		# the repost reads the account from the setting itself, so it must already hold NEW
		doctype = TARGETS[target][0]
		current = frappe.db.get_value(doctype, change["name"], change["field"])
		if current != change["new"]:
			return _("Simpan dulu {0} {1} ke {2} sebelum mengupdate jurnal lama").format(
				_(doctype), change["name"], change["new"]
			)
	return None


def _change_key(change) -> dict:
	return {k: change.get(k) for k in ("name", "company", "field", "old", "new")}


@frappe.whitelist()
def preview(target: str, changes, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
	"""Per change: how many submitted vouchers would be updated and which are skipped (and why)."""
	_check_permission(target)
	blockers = _Blockers()
	out = []
	for change in _parse(changes):
		if err := _validate_change(target, change):
			out.append({**_change_key(change), "error": err, "count": 0, "vouchers": [], "skipped": []})
			continue
		plan = _plan_change(target, change, from_date, to_date, blockers)
		out.append(
			{
				**_change_key(change),
				"count": len(plan["ready"]),
				"vouchers": [
					{k: v[k] for k in ("voucher_type", "voucher_no", "posting_date")}
					for v in plan["ready"][:20]
				],
				"skipped": plan["skipped"],
			}
		)
	return out


@frappe.whitelist(methods=["POST"])
def apply(target: str, changes, from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Swap OLD for NEW on the vouchers and queue their repost; big runs go to a background job."""
	_check_permission(target)
	changes = _parse(changes)
	blockers = _Blockers()
	total = sum(
		len(_plan_change(target, c, from_date, to_date, blockers)["ready"])
		for c in changes
		if not _validate_change(target, c)
	)
	if total <= SYNC_LIMIT:
		return {"results": apply_changes(target, changes, from_date, to_date)}

	job_id = f"bac_ledger_{uuid.uuid4().hex[:12]}"
	frappe.enqueue(
		"account_bulk_config.api.ledger_update.run_job",
		queue="long",
		timeout=3600,
		job_id=job_id,
		bac_job_id=job_id,
		target=target,
		changes=changes,
		from_date=from_date,
		to_date=to_date,
		user=frappe.session.user,
	)
	return {"job_id": job_id, "total": total}


def run_job(target, changes, from_date, to_date, user, bac_job_id=None, job_id=None) -> None:
	results = apply_changes(target, changes, from_date, to_date)
	frappe.publish_realtime(
		"bulk_account_config_ledger_done",
		{"job_id": bac_job_id or job_id, "results": results},
		user=user,
	)


def apply_changes(target, changes, from_date=None, to_date=None) -> list[dict]:
	"""Update the documents of every change and create the repost documents for them."""
	_check_permission(target)
	blockers = _Blockers()
	results = []
	for change in _parse(changes):
		if err := _validate_change(target, change):
			results.append({**_change_key(change), "status": "error", "message": err})
			continue
		plan = _plan_change(target, change, from_date, to_date, blockers)
		results.append(_apply_plan(change, plan))
	return results


def _apply_plan(change, plan) -> dict:
	note = _("Bulk Account Config: {0} diganti dari {1} ke {2}").format(
		change["field"], change["old"], change["new"]
	)
	updated, failed, reposts = 0, [], []

	gl_vouchers = [v for v in plan["ready"] if not v["stock"]]
	batches = [gl_vouchers[i : i + REPOST_CHUNK] for i in range(0, len(gl_vouchers), REPOST_CHUNK)]
	# a stock voucher gets a Repost Item Valuation of its own
	batches += [[v] for v in plan["ready"] if v["stock"]]

	for batch in batches:
		# the swap and its repost stand or fall together
		sp = f"bac_{uuid.uuid4().hex[:8]}"
		frappe.db.savepoint(sp)
		try:
			for v in batch:
				_swap(change, v, note)
			if batch[0]["stock"]:
				reposts.append(_repost_stock_voucher(change["company"], batch[0]))
			else:
				reposts.append(_repost_ledger(change["company"], batch))
			frappe.db.release_savepoint(sp)
			updated += len(batch)
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback(save_point=sp)
			msg = _error_message(e)
			failed.extend({**_voucher_ref(v), "reason": msg} for v in batch)

	return {
		**_change_key(change),
		"status": "error" if failed and not updated else "ok",
		"updated": updated,
		"skipped": plan["skipped"],
		"failed": failed,
		"reposts": reposts,
	}


def _swap(change, v, note) -> None:
	for doctype, rowname, field in v["rows"]:
		frappe.db.set_value(doctype, rowname, field, change["new"], update_modified=False)
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": v["voucher_type"],
			"reference_name": v["voucher_no"],
			"content": note,
		}
	).insert(ignore_permissions=True)


def _voucher_ref(v) -> dict:
	return {k: v[k] for k in ("voucher_type", "voucher_no", "posting_date")}


def _repost_ledger(company, vouchers) -> dict:
	doc = frappe.new_doc("Repost Accounting Ledger")
	doc.company = company
	for v in vouchers:
		doc.append("vouchers", {"voucher_type": v["voucher_type"], "voucher_no": v["voucher_no"]})
	doc.insert()
	doc.submit()
	return {"doctype": doc.doctype, "name": doc.name, "count": len(vouchers)}


def _repost_stock_voucher(company, v) -> dict:
	doc = frappe.get_doc(
		{
			"doctype": "Repost Item Valuation",
			"based_on": "Transaction",
			"voucher_type": v["voucher_type"],
			"voucher_no": v["voucher_no"],
			"posting_date": v["posting_date"],
			"posting_time": v["posting_time"],
			"company": company,
			"repost_only_accounting_ledgers": 1,
		}
	)
	doc.insert()
	doc.submit()
	return {"doctype": doc.doctype, "name": doc.name, "count": 1}


def _error_message(exc: Exception) -> str:
	from account_bulk_config.api.batch import _extract_error_message

	return _extract_error_message(exc)
