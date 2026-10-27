"""Copy a parent company's chart of accounts to its child companies.

ERPNext copies a new account of a root company to every descendant inside the same save, one
nested-set insert per company, and throws when a child misses the parent account. With many
children (or a large Account table) that single request can run past the web timeout. Here the
copy runs in a background job: missing accounts are created parents first, existing ones get the
fields ERPNext keeps in sync, and problems are reported per company instead of failing the save.
"""

import erpnext
import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.nestedset import get_ancestors_of, get_descendants_of

# the fields ERPNext pushes from a parent account to its existing copies
SYNC_FIELDS = ("account_type", "freeze_account", "balance_must_be")
SYNC_LIMIT = 30
FIELDS = [
	"name",
	"account_name",
	"account_number",
	"parent_account",
	"is_group",
	"root_type",
	"account_currency",
	*SYNC_FIELDS,
]


def _check_permission():
	if not frappe.has_permission("Account", "create"):
		frappe.throw(_("Butuh izin membuat Account untuk menyalin COA."), frappe.PermissionError)


def _children(parent_company: str, companies=None) -> list[str]:
	descendants = get_descendants_of("Company", parent_company)
	if companies:
		companies = frappe.parse_json(companies) if isinstance(companies, str) else companies
		return [c for c in descendants if c in set(companies)]
	return descendants


def _accounts(company: str) -> list[dict]:
	return frappe.get_all("Account", filters={"company": company}, fields=FIELDS, order_by="lft")


def _match(index: dict, src: dict) -> dict | None:
	"""The child's copy of src, matched the way ERPNext does: same name, and same number if src has one."""
	candidates = index.get(src.account_name) or []
	if src.account_number:
		candidates = [c for c in candidates if c.account_number == src.account_number]
	else:
		# prefer the unnumbered one when the child numbered its own copy differently
		candidates = sorted(candidates, key=lambda c: bool(c.account_number))
	return candidates[0] if candidates else None


def _label(acc: dict) -> str:
	return f"{acc.account_number} - {acc.account_name}" if acc.account_number else acc.account_name


def _with_ancestors(source: list[dict], names) -> list[dict]:
	by_name = {a.name: a for a in source}
	wanted = set()
	for name in names:
		while name and name not in wanted:
			wanted.add(name)
			name = by_name[name].parent_account if name in by_name else None
	return [a for a in source if a.name in wanted]


def _plan_company(source: list[dict], company: str, update_existing: bool) -> dict:
	index = {}
	for acc in _accounts(company):
		index.setdefault(acc.account_name, []).append(acc)

	# source account name -> its copy in the child: an existing account or one created below
	mapped = {}
	create, update, issues = [], [], []
	for src in source:
		parent = mapped.get(src.parent_account) if src.parent_account else None
		if src.parent_account and not parent:
			# an ancestor already failed; it is reported there
			continue
		if parent and not parent["is_group"]:
			issues.append(
				_("{0}: induknya {1} di {2} berupa ledger, bukan grup").format(
					_label(src), parent["name"], company
				)
			)
			continue

		if existing := _match(index, src):
			if cint(existing.is_group) != cint(src.is_group):
				issues.append(
					_("{0}: di {1} berupa {2}, di parent berupa {3}").format(
						_label(src),
						company,
						_("grup") if existing.is_group else _("ledger"),
						_("grup") if src.is_group else _("ledger"),
					)
				)
				continue
			mapped[src.name] = {"name": existing.name, "is_group": existing.is_group}
			diff = {f: src[f] for f in SYNC_FIELDS if (existing[f] or "") != (src[f] or "")}
			if update_existing and diff:
				update.append({"account": existing.name, "label": _label(src), "values": diff})
			continue

		mapped[src.name] = {"name": f"(baru) {_label(src)}", "is_group": src.is_group}
		create.append(
			{
				"source": src.name,
				"label": _label(src),
				"parent": src.parent_account,
				"parent_label": parent["name"] if parent else None,
			}
		)
	return {"company": company, "create": create, "update": update, "issues": issues}


def _plan(parent_company, companies=None, accounts=None, update_existing=True) -> list[dict]:
	if get_ancestors_of("Company", parent_company):
		frappe.throw(_("{0} bukan company induk teratas").format(parent_company))
	source = _accounts(parent_company)
	if accounts:
		source = _with_ancestors(source, accounts)
	return [_plan_company(source, c, cint(update_existing)) for c in _children(parent_company, companies)]


@frappe.whitelist()
def get_children(parent_company: str) -> list[str]:
	return _children(parent_company)


@frappe.whitelist()
def preview(parent_company: str, companies=None, update_existing: int = 1) -> list[dict]:
	"""Per child company: the accounts that would be created or updated, and the ones that cannot."""
	_check_permission()
	return _plan(parent_company, companies, update_existing=update_existing)


@frappe.whitelist(methods=["POST"])
def apply(parent_company: str, companies=None, update_existing: int = 1) -> dict:
	"""Small copies run right away; bigger ones go to a background job that reports by realtime."""
	_check_permission()
	plans = _plan(parent_company, companies, update_existing=update_existing)
	total = sum(len(p["create"]) + len(p["update"]) for p in plans)
	if total <= SYNC_LIMIT:
		return {"results": _apply_plans(parent_company, plans)}

	job_id = f"bac_coa_{frappe.generate_hash(length=12)}"
	frappe.enqueue(
		"account_bulk_config.api.coa_sync.run_job",
		queue="long",
		timeout=3600,
		job_id=job_id,
		bac_job_id=job_id,
		parent_company=parent_company,
		companies=[p["company"] for p in plans],
		update_existing=update_existing,
		user=frappe.session.user,
	)
	return {"job_id": job_id, "total": total}


def run_job(
	parent_company, companies=None, accounts=None, update_existing=1, user=None, bac_job_id=None, job_id=None
) -> None:
	plans = _plan(parent_company, companies, accounts, update_existing)
	# in tests the job runs inline (now=True) and must stay inside the test's transaction
	results = _apply_plans(parent_company, plans, commit=not frappe.in_test)
	frappe.publish_realtime(
		"bulk_account_config_coa_done",
		{
			"job_id": bac_job_id,
			"parent_company": parent_company,
			# set when the job follows an account saved in the parent rather than the copy dialog
			"account": accounts[0] if accounts else None,
			"results": results,
		},
		user=user,
	)


def _apply_plans(parent_company: str, plans: list[dict], commit: bool = False) -> list[dict]:
	results = []
	parent_currency = erpnext.get_company_currency(parent_company)
	for plan in plans:
		result = {
			"company": plan["company"],
			"created": 0,
			"updated": 0,
			"issues": list(plan["issues"]),
			"error": None,
		}
		if not plan["create"] and not plan["update"]:
			results.append(result)
			continue
		frappe.db.savepoint("bac_coa_sync")
		try:
			result["created"] = _create(plan, parent_currency)
			for row in plan["update"]:
				doc = frappe.get_doc("Account", row["account"])
				doc.update(row["values"])
				doc.flags.ignore_root_company_validation = True
				doc.save()
				result["updated"] += 1
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback(save_point="bac_coa_sync")
			result.update(created=0, updated=0, error=_error_message(e))
		else:
			if commit:
				frappe.db.commit()
		frappe.clear_messages()
		results.append(result)
	return results


def _create(plan: dict, parent_currency: str) -> int:
	company = plan["company"]
	currency = erpnext.get_company_currency(company)
	index = {}
	for acc in _accounts(company):
		index.setdefault(acc.account_name, []).append(acc)
	created = {}
	for row in plan["create"]:
		src = frappe.get_doc("Account", row["source"])
		parent = None
		if src.parent_account:
			parent = (
				created.get(src.parent_account)
				or _match(
					index,
					frappe._dict(frappe.db.get_value("Account", src.parent_account, FIELDS, as_dict=True)),
				).name
			)
		doc = frappe.copy_doc(src)
		doc.update(
			{
				"company": company,
				"parent_account": parent,
				# an account kept in a foreign currency stays so; others take the child's currency
				"account_currency": src.account_currency
				if src.account_currency and src.account_currency != parent_currency
				else currency,
				"lft": None,
				"rgt": None,
				"old_parent": None,
			}
		)
		doc.flags.ignore_root_company_validation = True
		doc.insert()
		created[src.name] = doc.name
	return len(created)


def _error_message(exc: Exception) -> str:
	from account_bulk_config.api.batch import _extract_error_message

	return _extract_error_message(exc)


# -- creating an account in the parent: copy it to the children in the background --------------


def _defers(doc) -> bool:
	if doc.flags.ignore_root_company_validation or frappe.local.flags.ignore_root_company_validation:
		return False
	if not doc.parent_account or frappe.local.flags.allow_unverified_charts:
		return False
	if get_ancestors_of("Company", doc.company):
		return False
	return bool(get_descendants_of("Company", doc.company))


def before_validate(doc, method=None):
	"""Keep ERPNext from copying the account to every child company inside this request."""
	if _defers(doc):
		doc.flags.ignore_root_company_validation = True
		doc.flags.bac_sync_children = True


def on_update(doc, method=None):
	if not doc.flags.bac_sync_children:
		return
	before = doc.get_doc_before_save()
	if before and all((before.get(f) or "") == (doc.get(f) or "") for f in SYNC_FIELDS):
		return
	frappe.enqueue(
		"account_bulk_config.api.coa_sync.run_job",
		queue="default",
		timeout=1800,
		enqueue_after_commit=True,
		now=frappe.in_test,
		parent_company=doc.company,
		accounts=[doc.name],
		user=frappe.session.user,
	)
	frappe.msgprint(
		_("Akun disalin ke anak perusahaan di background; hasilnya muncul sebagai notifikasi."),
		alert=True,
		indicator="blue",
	)
