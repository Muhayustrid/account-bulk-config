"""API for bulk company accounts (Page 1)."""

import frappe
from frappe.utils import cint

from account_bulk_config.api.fields import COMPANY_FIELDS

COMPANY_FIELDNAMES = [f["fieldname"] for f in COMPANY_FIELDS]


@frappe.whitelist()
def get_rows(
	parent_company: str | None = None,
	search: str | None = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Return company rows with account defaults, hierarchy info, and pagination."""
	start = max(0, cint(start))
	page_len = cint(page_length) if page_length is not None else 20

	filters = []
	or_filters = []

	if parent_company:
		parent_info = frappe.db.get_value("Company", parent_company, ["lft", "rgt"], as_dict=True)
		if not parent_info:
			return {"rows": [], "total": 0}
		filters.append(["lft", ">=", parent_info.lft])
		filters.append(["rgt", "<=", parent_info.rgt])

	if search and search.strip():
		s = f"%{search.strip()}%"
		or_filters.append(["name", "like", s])
		or_filters.append(["abbr", "like", s])

	matching_companies = frappe.get_all(
		"Company",
		filters=filters,
		or_filters=or_filters,
		order_by="lft asc",
		pluck="name",
	)

	total = len(matching_companies)
	if not total:
		return {"rows": [], "total": 0}

	all_parents = dict(frappe.get_all("Company", fields=["name", "parent_company"], as_list=True))

	def get_depth(name: str) -> int:
		d = 0
		curr = name
		seen = {curr}
		while all_parents.get(curr):
			curr = all_parents[curr]
			if curr in seen:
				break
			seen.add(curr)
			d += 1
		return d

	base_depth = get_depth(matching_companies[0])
	if page_length is not None and page_len == 0:
		paged_names = matching_companies[start:]
	else:
		paged_names = matching_companies[start : start + max(1, page_len)]
	if not paged_names:
		return {"rows": [], "total": total}

	fields_to_fetch = ["name", "abbr", "is_group", "parent_company"] + COMPANY_FIELDNAMES
	companies_data = frappe.get_all(
		"Company",
		filters={"name": ["in", paged_names]},
		fields=fields_to_fetch,
	)
	data_by_name = {c["name"]: c for c in companies_data}

	from collections import Counter

	child_counts = Counter(all_parents.values())

	rows = []
	for name in paged_names:
		row = data_by_name.get(name, {})
		row["child_count"] = child_counts.get(name, 0)
		row["indent"] = max(0, get_depth(name) - base_depth)
		rows.append(row)

	return {"rows": rows, "total": total}
