"""Account mapping and company descendant resolution for bulk account configuration."""

import json

import frappe
from frappe import _

from account_bulk_config.api.batch import TARGETS
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
	if not src_abbr or not dst_abbr:
		return (None, False)

	suffix = f" - {src_abbr}"
	if not value.endswith(suffix):
		return (None, False)

	mapped = f"{value[: -len(suffix)]} - {dst_abbr}"
	doc_company = frappe.db.get_value(link, mapped, "company")
	found = bool(doc_company and doc_company == dst_company)
	return (mapped, found)


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

	results = []

	for c in changes:
		src_company = c.get("company")
		if not src_company:
			continue

		field_name = c.get("field")
		if field_name not in field_map:
			continue

		link_doctype = field_map[field_name]["link"]

		if targets is not None:
			child_companies = [comp for comp in targets if comp != src_company]
		else:
			is_group = frappe.get_cached_value("Company", src_company, "is_group")
			if not is_group:
				continue
			child_companies = descendants(src_company, depth)

		old_val = c.get("old") or None
		new_val = c.get("new") or None

		for child in child_companies:
			mapped_old, _ = map_value(link_doctype, old_val, src_company, child)
			mapped_new, found = map_value(link_doctype, new_val, src_company, child)

			if target == "company":
				current = frappe.db.get_value("Company", child, field_name) or None
				out_name = child
			else:
				parenttype = doctype
				parent_name = c.get("name")
				current = (
					frappe.db.get_value(
						"Item Default",
						{"parenttype": parenttype, "parent": parent_name, "company": child},
						field_name,
					)
					or None
				)
				out_name = parent_name

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
