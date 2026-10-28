"""Copy a parent company's chart of accounts to its child companies.

ERPNext copies a new account of a root company to every descendant inside the same save, one
nested-set insert per company, and throws when a child misses the parent account. With many
children (or a large Account table) that single request can run past the web timeout. Here the
copy runs in a background job: missing accounts are created parents first, existing ones get the
fields ERPNext keeps in sync (plus their place in the tree and their number), accounts the parent
no longer has can be deleted, and problems are reported per account instead of failing the save.
"""

import erpnext
import frappe
from frappe import _
from frappe.utils import cint, cstr, sbool
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
	"lft",
	"rgt",
	*SYNC_FIELDS,
]


def _check_permission(delete_missing=0):
	if not frappe.has_permission("Account", "create"):
		frappe.throw(_("Butuh izin membuat Account untuk menyalin COA."), frappe.PermissionError)
	if cint(delete_missing) and not frappe.has_permission("Account", "delete"):
		frappe.throw(_("Butuh izin menghapus Account untuk menghapus akun di anak."), frappe.PermissionError)


def _children(parent_company: str, companies=None) -> list[str]:
	descendants = get_descendants_of("Company", parent_company)
	if companies:
		companies = frappe.parse_json(companies) if isinstance(companies, str) else companies
		return [c for c in descendants if c in set(companies)]
	return descendants


def _accounts(company: str) -> list[dict]:
	return frappe.get_all("Account", filters={"company": company}, fields=FIELDS, order_by="lft")


def _number(acc: dict) -> str:
	return cstr(acc.account_number).strip()


def _matches(source: list[dict], accounts: list[dict]) -> dict:
	"""Source account name -> the child's copy of it, each child account used once.

	Same name and number first, so a fuzzier match never steals an exact one; then same name only:
	a parent account renumbered after it was copied, or a child that numbered its own copy.
	"""
	by_name = {}
	for acc in accounts:
		by_name.setdefault(acc.account_name, []).append(acc)

	out, taken = {}, set()

	def pick(src, candidates):
		for c in candidates:
			if c.name not in taken:
				taken.add(c.name)
				out[src.name] = c
				return

	for src in source:
		pick(src, [c for c in by_name.get(src.account_name) or [] if _number(c) == _number(src)])
	for src in source:
		if src.name not in out:
			# prefer the unnumbered one when the child numbered its own copy differently
			pick(src, sorted(by_name.get(src.account_name) or [], key=lambda c: bool(_number(c))))
	return out


def _norm(field: str, value) -> str:
	# a blank freeze_account means "No", ERPNext's default
	return value or ("No" if field == "freeze_account" else "")


def _label(acc: dict) -> str:
	return f"{_number(acc)} - {acc.account_name}" if _number(acc) else acc.account_name


def _with_ancestors(source: list[dict], names) -> list[dict]:
	by_name = {a.name: a for a in source}
	wanted = set()
	for name in names:
		while name and name not in wanted:
			wanted.add(name)
			name = by_name[name].parent_account if name in by_name else None
	return [a for a in source if a.name in wanted]


def _plan_company(
	source: list[dict], company: str, update_existing: bool, delete_missing: bool = False
) -> dict:
	accounts = _accounts(company)
	matches = _matches(source, accounts)
	numbers = {_number(a): a.name for a in accounts if _number(a)}

	# source account name -> its copy in the child: an existing account or one created below
	mapped = {}
	create, update, issues = [], [], []
	# child accounts holding a number the parent uses elsewhere: reported, so never deleted
	conflicts = set()
	for src in source:
		parent = mapped.get(src.parent_account) if src.parent_account else None
		if src.parent_account and not parent:
			# an ancestor already failed; it is reported there
			continue
		if parent and not parent["is_group"]:
			issues.append(
				_("{0}: induknya {1} di {2} berupa ledger, bukan grup").format(
					_label(src), parent["label"], company
				)
			)
			continue

		existing = matches.get(src.name)
		if not existing:
			if _number(src) and _number(src) in numbers:
				conflicts.add(numbers[_number(src)])
				issues.append(
					_("{0}: nomor akun {1} di {2} sudah dipakai {3}").format(
						_label(src), _number(src), company, numbers[_number(src)]
					)
				)
				continue
			mapped[src.name] = {
				"name": None,
				"source": src.name,
				"label": _label(src),
				"is_group": src.is_group,
			}
			create.append(
				{
					"source": src.name,
					"label": _label(src),
					"parent_account": parent and parent["name"],
					"parent_source": parent and parent["source"],
					"parent_label": parent and parent["label"],
				}
			)
			continue

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
		mapped[src.name] = {
			"name": existing.name,
			"source": None,
			"label": existing.name,
			"is_group": existing.is_group,
		}
		if not update_existing:
			continue

		row = {"account": existing.name, "label": _label(src), "values": {}, "changes": []}
		for f in SYNC_FIELDS:
			if _norm(f, existing[f]) != _norm(f, src[f]):
				row["values"][f] = src[f]
				row["changes"].append(f"{f}: {existing[f] or '-'} → {src[f] or '-'}")
		if _number(src) and _number(src) != _number(existing):
			if numbers.get(_number(src), existing.name) != existing.name:
				conflicts.add(numbers[_number(src)])
				issues.append(
					_("{0}: nomor akun {1} di {2} sudah dipakai {3}").format(
						_label(src), _number(src), company, numbers[_number(src)]
					)
				)
			else:
				row["account_number"] = _number(src)
				row["changes"].append(f"account_number: {_number(existing) or '-'} → {_number(src)}")
		if parent and (parent["source"] or parent["name"] != existing.parent_account):
			row["parent_account"] = parent["name"]
			row["parent_source"] = parent["source"]
			row["changes"].append(f"parent_account: {existing.parent_account} → {parent['label']}")
		if row["changes"]:
			update.append(row)

	delete = _deletable(accounts, matches, conflicts) if delete_missing else []
	return {"company": company, "create": create, "update": update, "delete": delete, "issues": issues}


def _deletable(accounts: list[dict], matches: dict, conflicts: set) -> list[dict]:
	"""Child accounts with no counterpart in the parent, deepest first; groups only when emptied."""
	kept_names = conflicts | {a.name for a in matches.values()}
	kept = [a for a in accounts if a.name in kept_names]
	missing = [a for a in accounts if a.parent_account and a.name not in kept_names]
	# a group that still holds a kept account stays
	missing = [a for a in missing if not a.is_group or not any(a.lft < k.lft and k.rgt < a.rgt for k in kept)]
	return [{"account": a.name, "label": a.name} for a in sorted(missing, key=lambda a: -a.lft)]


def _plan(
	parent_company, companies=None, accounts=None, update_existing=True, delete_missing=False
) -> list[dict]:
	source = _accounts(parent_company)
	if accounts:
		source = _with_ancestors(source, accounts)
		# a partial source says nothing about which child accounts are gone
		delete_missing = False
	return [
		_plan_company(source, c, cint(update_existing), cint(delete_missing))
		for c in _children(parent_company, companies)
	]


def _size(plans: list[dict]) -> int:
	return sum(len(p["create"]) + len(p["update"]) + len(p["delete"]) for p in plans)


@frappe.whitelist()
def get_children(parent_company: str) -> list[str]:
	return _children(parent_company)


@frappe.whitelist()
def preview(
	parent_company: str, companies=None, update_existing: int = 1, delete_missing: int = 0
) -> list[dict]:
	"""Per child company: the accounts that would be created, updated or deleted, and the ones that cannot."""
	_check_permission(delete_missing)
	return _plan(parent_company, companies, update_existing=update_existing, delete_missing=delete_missing)


@frappe.whitelist(methods=["POST"])
def apply(parent_company: str, companies=None, update_existing: int = 1, delete_missing: int = 0) -> dict:
	"""Small copies run right away; bigger ones go to a background job that reports by realtime."""
	_check_permission(delete_missing)
	plans = _plan(parent_company, companies, update_existing=update_existing, delete_missing=delete_missing)
	total = _size(plans)
	# renumbering renames the account and every link to it, too slow for a web request
	renames = any("account_number" in u for p in plans for u in p["update"])
	if total <= SYNC_LIMIT and not renames:
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
		delete_missing=delete_missing,
		user=frappe.session.user,
	)
	return {"job_id": job_id, "total": total}


def run_job(
	parent_company,
	companies=None,
	accounts=None,
	update_existing=1,
	delete_missing=0,
	user=None,
	bac_job_id=None,
	job_id=None,
) -> None:
	error = None
	try:
		plans = _plan(parent_company, companies, accounts, update_existing, delete_missing)
		# in tests the job runs inline (now=True) and must stay inside the test's transaction
		results = _apply_plans(parent_company, plans, commit=not frappe.in_test)
	except Exception as e:  # noqa: BLE001
		# without a notice the dialog would wait forever; the job log keeps the traceback
		results, error = [], _error_message(e)
		frappe.log_error(_("Salin COA {0} gagal").format(parent_company))
		if not frappe.in_test:
			frappe.db.rollback()
	frappe.publish_realtime(
		"bulk_account_config_coa_done",
		{
			"job_id": bac_job_id,
			"parent_company": parent_company,
			# set when the job follows an account saved in the parent rather than the copy dialog
			"account": accounts[0] if accounts else None,
			"results": results,
			"error": error,
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
			"deleted": 0,
			"issues": list(plan["issues"]),
			"error": None,
		}
		if plan["create"] or plan["update"] or plan["delete"]:
			_apply_company(plan, parent_currency, result)
			if commit:
				frappe.db.commit()
		frappe.clear_messages()
		results.append(result)
	return results


def _apply_company(plan: dict, parent_currency: str, result: dict) -> None:
	"""Each account in its own savepoint: one that ERPNext refuses is reported, the rest still go."""
	company = plan["company"]
	currency = erpnext.get_company_currency(company)
	# names change when an account is renumbered; source name -> child name for created accounts
	renamed, created = {}, {}

	def run(label, fn):
		frappe.db.savepoint("bac_coa_sync")
		try:
			fn()
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback(save_point="bac_coa_sync")
			result["issues"].append(f"{label}: {_error_message(e)}")
			return False
		frappe.db.release_savepoint("bac_coa_sync")
		return True

	def parent_of(row):
		if row.get("parent_source"):
			return created.get(row["parent_source"])
		return renamed.get(row["parent_account"], row["parent_account"])

	updated = set()
	for row in plan["update"]:
		if "account_number" in row and run(row["label"], lambda row=row: _renumber(row, renamed)):
			updated.add(row["account"])

	for row in plan["create"]:
		parent = parent_of(row)
		if row["parent_source"] and not parent:
			result["issues"].append(
				_("{0}: induknya {1} gagal dibuat").format(row["label"], row["parent_label"])
			)
			continue
		if run(
			row["label"],
			lambda row=row, parent=parent: _create(row, parent, company, currency, parent_currency, created),
		):
			result["created"] += 1

	for row in plan["update"]:
		values = dict(row["values"])
		if "parent_account" in row:
			parent = parent_of(row)
			if not parent:
				result["issues"].append(_("{0}: induk barunya gagal dibuat").format(row["label"]))
			else:
				values["parent_account"] = parent
		account = renamed.get(row["account"], row["account"])
		if values and run(row["label"], lambda account=account, values=values: _update(account, values)):
			updated.add(row["account"])
	result["updated"] = len(updated)

	for row in plan["delete"]:
		if run(row["label"], lambda row=row: frappe.delete_doc("Account", row["account"])):
			result["deleted"] += 1


def _create(row, parent, company, currency, parent_currency, created) -> None:
	src = frappe.get_doc("Account", row["source"])
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


def _update(account: str, values: dict) -> None:
	doc = frappe.get_doc("Account", account)
	doc.update(values)
	doc.flags.ignore_root_company_validation = True
	doc.save()


def _renumber(row: dict, renamed: dict) -> None:
	account = row["account"]
	new_name = _rename(
		account, frappe.db.get_value("Account", account, "account_name"), row["account_number"]
	)
	if new_name != account:
		renamed[account] = new_name


def _rename(account: str, account_name: str, account_number: str | None) -> str:
	"""Set an account's name and number and rename the document to match, as ERPNext does."""
	from erpnext.accounts.utils import get_autoname_with_number

	account_name, account_number = account_name.strip(), cstr(account_number).strip()
	doc = frappe.get_doc("Account", account)
	doc.validate_account_number(account_number)
	frappe.db.set_value("Account", account, {"account_name": account_name, "account_number": account_number})
	new_name = get_autoname_with_number(account_number, account_name, doc.company)
	if new_name != account:
		frappe.rename_doc("Account", account, new_name, force=True, show_alert=False)
	return new_name


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
	if (
		before
		and before.parent_account == doc.parent_account
		and all(_norm(f, before.get(f)) == _norm(f, doc.get(f)) for f in SYNC_FIELDS)
	):
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


# -- renaming an account in the parent: rename its copies in the background ---------------------


@frappe.whitelist()
def update_account_number(name, account_name, account_number=None, from_descendant=False):
	"""ERPNext's update_account_number, minus renaming every child company's copy in this request.

	ERPNext renames the copies one rename_doc each (every link to the account rewritten) inside the
	same request, which times out with many child companies. The parent account is renamed here,
	its copies by a background job.
	"""
	from erpnext.accounts.doctype.account import account as erpnext_account

	account = frappe.get_doc("Account", name)
	descendants = get_descendants_of("Company", account.company)
	if sbool(from_descendant) or not descendants:
		return erpnext_account.update_account_number(name, account_name, account_number, from_descendant)

	account.check_permission("write")
	old_name, old_number = account.account_name, account.account_number
	_check_rename_in_ancestors(account)
	# from_descendant=True: ERPNext then renames this account only; the ancestor check is done above
	new_name = erpnext_account.update_account_number(name, account_name, account_number, from_descendant=True)
	if (old_name, cstr(old_number)) == (cstr(account_name).strip(), cstr(account_number).strip()):
		return new_name

	frappe.enqueue(
		"account_bulk_config.api.coa_sync.run_rename_job",
		queue="long",
		timeout=3600,
		enqueue_after_commit=True,
		now=frappe.in_test,
		company=account.company,
		old_name=old_name,
		old_number=old_number,
		account_name=account_name,
		account_number=account_number,
		account=new_name or name,
		user=frappe.session.user,
	)
	frappe.msgprint(
		_("Nama/nomor akun di anak perusahaan diganti di background; hasilnya muncul sebagai notifikasi."),
		alert=True,
		indicator="blue",
	)
	return new_name


def _check_rename_in_ancestors(account) -> None:
	# the same refusal ERPNext gives before renaming an account its parent company also has
	if not get_ancestors_of("Company", account.company) or frappe.get_cached_value(
		"Company", account.company, "allow_account_creation_against_child_company"
	):
		return
	for ancestor in get_ancestors_of("Company", account.company):
		if frappe.db.get_value(
			"Account",
			{
				"account_number": account.account_number,
				"account_name": account.account_name,
				"company": ancestor,
			},
			"name",
		):
			frappe.throw(
				_("Account {0} exists in parent company {1}.").format(
					frappe.bold(account.account_name), frappe.bold(ancestor)
				)
				+ "<br>"
				+ _("Renaming it is only allowed via parent company {0}, to avoid mismatch.").format(
					frappe.bold(ancestor)
				)
				+ "<br><br>"
				+ _("To overrule this, enable '{0}' in company {1}").format(
					_("Allow Account Creation Against Child Company"), frappe.bold(account.company)
				),
				title=_("Rename Not Allowed"),
			)


def run_rename_job(company, old_name, old_number, account_name, account_number, account, user=None) -> None:
	"""Rename the child companies' copies, matched the way ERPNext does: old name, and old number if any."""
	filters = {"company": ["in", get_descendants_of("Company", company)], "account_name": old_name}
	if old_number:
		filters["account_number"] = old_number
	results = []
	for copy in frappe.get_all("Account", filters=filters, fields=["name", "company"], order_by="lft"):
		result = {
			"company": copy.company,
			"created": 0,
			"updated": 0,
			"deleted": 0,
			"issues": [],
			"error": None,
		}
		frappe.db.savepoint("bac_coa_rename")
		try:
			_rename(copy.name, account_name, account_number)
			result["updated"] = 1
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback(save_point="bac_coa_rename")
			result["issues"].append(f"{copy.name}: {_error_message(e)}")
		else:
			frappe.db.release_savepoint("bac_coa_rename")
		# in tests the job runs inline (now=True) and must stay inside the test's transaction
		if not frappe.in_test:
			frappe.db.commit()
		frappe.clear_messages()
		results.append(result)
	frappe.publish_realtime(
		"bulk_account_config_coa_done",
		{"job_id": None, "parent_company": company, "account": account, "results": results, "error": None},
		user=user,
	)
