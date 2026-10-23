"""Account mapping and company descendant resolution for bulk account configuration."""

import json

import frappe
from frappe import _

from account_bulk_config.api.batch import CHILD_DOCTYPES, TARGETS
from account_bulk_config.api.fields import COMPANY_SCOPED


def map_value(link: str, value: str | None, src_company: str, dst_company: str) -> tuple[str | None, bool]:
	"""Map a linked document name from src_company to dst_company.

	Returns (mapped_value, found).
	- Empty value -> (None, True).
	- Non-company-scoped link -> (value, True).
	- Company-scoped: if value does not end with ' - <src_abbr>', returns (None, False).
	  Otherwise replaces suffix with ' - <dst_abbr>' and checks if document exists in dst_company.
	"""
	if not value:
		return (None, True)

	if link not in COMPANY_SCOPED:
		return (value, True)

	src_abbr = frappe.get_cached_value("Company", src_company, "abbr")
	dst_abbr = frappe.get_cached_value("Company", dst_company, "abbr")
	mapped = _swap_abbr(value, src_abbr, dst_abbr)
	if mapped is None:
		return (None, False)

	doc_company = frappe.db.get_value(link, mapped, "company")
	found = bool(doc_company and doc_company == dst_company)
	return (mapped, found)


def _swap_abbr(value: str, src_abbr: str | None, dst_abbr: str | None) -> str | None:
	"""Replace the ' - <src_abbr>' suffix with ' - <dst_abbr>'; None if it cannot be mapped."""
	if not src_abbr or not dst_abbr:
		return None
	suffix = f" - {src_abbr}"
	if not value.endswith(suffix):
		return None
	return f"{value[: -len(suffix)]} - {dst_abbr}"


def descendants(company: str, depth: str) -> list[str]:
	"""Return descendant company names in lft order.

	depth: 'children' for direct child companies, 'all' for all nested descendants.
	"""
	if depth == "children":
		return frappe.get_all(
			"Company",
			filters={"parent_company": company},
			pluck="name",
			order_by="lft asc",
		)
	if depth == "all":
		res = frappe.db.get_value("Company", company, ["lft", "rgt"])
		if not res:
			return []
		lft, rgt = res
		if not (lft and rgt) or rgt <= lft + 1:
			return []
		return frappe.get_all(
			"Company",
			filters={"lft": (">", lft), "rgt": ("<", rgt)},
			pluck="name",
			order_by="lft asc",
		)
	raise ValueError(f"Invalid depth: {depth}")


@frappe.whitelist()
def preview_propagation(
	target: str,
	changes: list[dict] | str,
	depth: str = "children",
	targets: list[str] | str | None = None,
) -> list[dict]:
	"""Return preview rows for propagating changes to child companies or specified target companies."""
	if target not in TARGETS:
		frappe.throw(_("Invalid target: {0}").format(target))

	if isinstance(changes, str):
		changes = json.loads(changes)
	if isinstance(targets, str):
		targets = json.loads(targets) if targets else None

	if not changes:
		return []

	doctype, _, field_defs = TARGETS[target]
	field_map = {f["fieldname"]: f for f in field_defs}

	# Every lookup below is one query for all changes, so preview cost does not grow per row.
	changes = [c for c in changes if c.get("company") and c.get("field") in field_map]
	src_companies = list(dict.fromkeys(c["company"] for c in changes))
	if targets is not None:
		children_of = {src: [comp for comp in targets if comp != src] for src in src_companies}
	else:
		groups = set(
			frappe.get_all("Company", filters={"name": ["in", src_companies], "is_group": 1}, pluck="name")
		) if src_companies else set()
		children_of = {src: descendants(src, depth) if src in groups else [] for src in src_companies}

	all_companies = set(src_companies).union(*children_of.values())
	if not any(children_of.values()):
		return []
	abbrs = dict(
		frappe.get_all("Company", filters={"name": ["in", list(all_companies)]}, fields=["name", "abbr"], as_list=True)
	)

	# 1. Map every value in memory and collect the names that must exist per link doctype
	pending = []
	wanted = {}
	for c in changes:
		src_company = c["company"]
		field_name = c["field"]
		link_doctype = field_map[field_name]["link"]
		old_val = c.get("old") or None
		new_val = c.get("new") or None
		for child in children_of[src_company]:
			if link_doctype in COMPANY_SCOPED:
				mapped_old = old_val and _swap_abbr(old_val, abbrs.get(src_company), abbrs.get(child))
				mapped_new = new_val and _swap_abbr(new_val, abbrs.get(src_company), abbrs.get(child))
				if mapped_new:
					wanted.setdefault(link_doctype, set()).add(mapped_new)
			else:
				mapped_old, mapped_new = old_val, new_val
			pending.append((c, child, link_doctype, mapped_old or None, mapped_new or None))

	owner = {}
	for link_doctype, names in wanted.items():
		for name, comp in frappe.get_all(
			link_doctype, filters={"name": ["in", list(names)]}, fields=["name", "company"], as_list=True
		):
			owner[(link_doctype, name)] = comp

	# 2. Current values of every target row in one query
	fieldnames = list(dict.fromkeys(c["field"] for c in changes))
	child_companies = list({p[1] for p in pending})
	if target == "company":
		current_rows = {
			(None, r["name"]): r
			for r in frappe.get_all(
				"Company", filters={"name": ["in", child_companies]}, fields=["name", *fieldnames]
			)
		}
	else:
		current_rows = {}
		for r in frappe.get_all(
			CHILD_DOCTYPES[target],
			filters={
				"parenttype": doctype,
				"parent": ["in", list({c.get("name") for c in changes})],
				"company": ["in", child_companies],
			},
			fields=["parent", "company", *fieldnames],
		):
			current_rows.setdefault((r["parent"], r["company"]), r)

	results = []
	for c, child, link_doctype, mapped_old, mapped_new in pending:
		field_name = c["field"]
		if target == "company":
			out_name = child
			row = current_rows.get((None, child))
		else:
			out_name = c.get("name")
			row = current_rows.get((out_name, child))
		current = (row or {}).get(field_name) or None

		found = (
			link_doctype not in COMPANY_SCOPED
			or not c.get("new")
			or bool(mapped_new and owner.get((link_doctype, mapped_new)) == child)
		)
		if not found:
			status = "not_found"
		elif current == mapped_new:
			status = "same"
		elif current in (None, mapped_old):
			status = "changed"
		else:
			status = "exception"

		results.append(
			{
				"name": out_name,
				"company": child,
				"field": field_name,
				"old": current,
				"new": mapped_new,
				"status": status,
				"checked": status == "changed",
			}
		)

	return results


@frappe.whitelist()
def preview_copy(
	target: str,
	src_company: str,
	fields: list[str] | str,
	item_group: str | None = None,
	item: str | None = None,
	mode_of_payment: str | None = None,
	targets: list[str] | str | None = None,
	depth: str = "children",
) -> dict:
	"""Copy preview of src_company's child-table defaults for every parent matching the page filters.

	No filter means every parent. Parents without a row in src_company have nothing to copy.
	Returns {"changes": source changes (old == new), "rows": preview_propagation rows}.
	"""
	if target not in CHILD_DOCTYPES:
		frappe.throw(_("Invalid target: {0}").format(target))
	if isinstance(fields, str):
		fields = json.loads(fields)
	if isinstance(targets, str):
		targets = json.loads(targets) if targets else None

	doctype, field_defs = TARGETS[target][0], TARGETS[target][2]
	wanted_fields = set(fields)
	fields = [f["fieldname"] for f in field_defs if f["fieldname"] in wanted_fields]
	empty = {"changes": [], "rows": []}
	if not fields:
		return empty

	filters = {"parenttype": doctype, "company": src_company}
	if target == "mode_of_payment":
		parent_filters = [["enabled", "=", 1]] + ([["name", "=", mode_of_payment]] if mode_of_payment else [])
	elif target == "item":
		parent_filters = [["disabled", "=", 0]] + ([["name", "=", item]] if item else [])
	else:
		parent_filters = []
	if item_group and target in ("item", "item_group"):
		ig = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
		if not ig:
			return empty
		subtree = [["lft", ">=", ig.lft], ["rgt", "<=", ig.rgt]]
		if target == "item_group":
			parent_filters += subtree
		else:
			groups = frappe.get_all("Item Group", filters=subtree, pluck="name")
			parent_filters.append(["item_group", "in", groups])
	if parent_filters:
		filters["parent"] = ["in", frappe.get_all(doctype, filters=parent_filters, pluck="name")]
		if not filters["parent"][1]:
			return empty

	changes = []
	seen = set()
	for r in frappe.get_all(
		CHILD_DOCTYPES[target], filters=filters, fields=["parent", *fields], order_by="parent asc, idx asc"
	):
		if r["parent"] in seen:
			continue
		seen.add(r["parent"])
		changes.extend(
			{"name": r["parent"], "company": src_company, "field": f, "old": r[f] or None, "new": r[f] or None}
			for f in fields
		)

	return {"changes": changes, "rows": preview_propagation(target, changes, depth, targets)}
