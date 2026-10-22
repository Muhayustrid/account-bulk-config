"""API for bulk Mode of Payment accounts configuration."""

import frappe
from frappe.utils import cint


@frappe.whitelist()
def get_rows(
	mode_of_payment: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Return paginated (Mode of Payment x Company) pairs with existing account defaults."""
	start = max(0, cint(start))
	page_len = cint(page_length) if page_length is not None else 20

	# 1. Determine parents (enabled Modes of Payment, ordered by name)
	mop_filters = [["enabled", "=", 1]]
	if mode_of_payment:
		mop_filters.append(["name", "=", mode_of_payment])

	parents = frappe.get_all(
		"Mode of Payment",
		filters=mop_filters,
		order_by="name asc",
		pluck="name",
	)

	# 2. Determine company list
	comp_filters = []
	if parent_company:
		parent_info = frappe.db.get_value("Company", parent_company, ["lft", "rgt"], as_dict=True)
		if not parent_info:
			return {"rows": [], "total": 0}
		comp_filters.append(["lft", ">=", parent_info.lft])
		comp_filters.append(["rgt", "<=", parent_info.rgt])
	if company:
		comp_filters.append(["name", "=", company])

	companies = frappe.get_all(
		"Company",
		filters=comp_filters,
		fields=["name", "is_group"],
		order_by="lft asc",
	)

	if not parents or not companies:
		return {"rows": [], "total": 0}

	num_companies = len(companies)
	total = len(parents) * num_companies

	if start >= total:
		return {"rows": [], "total": total}

	# 3. Slice pairs without materializing full product matrix
	if page_length is not None and page_len == 0:
		end = total
	else:
		end = min(total, start + max(1, page_len))
	sliced_pairs = []
	for idx in range(start, end):
		parent_idx = idx // num_companies
		comp_idx = idx % num_companies
		sliced_pairs.append((parents[parent_idx], companies[comp_idx]))

	# 4. Fetch existing child rows for sliced pairs in one query
	slice_parents = list(dict.fromkeys(p[0] for p in sliced_pairs))
	slice_companies = list(dict.fromkeys(p[1]["name"] for p in sliced_pairs))

	child_rows = frappe.get_all(
		"Mode of Payment Account",
		filters={
			"parenttype": "Mode of Payment",
			"parent": ["in", slice_parents],
			"company": ["in", slice_companies],
		},
		fields=["parent", "company", "default_account"],
	)

	child_by_pair = {}
	for r in child_rows:
		pair_key = (r["parent"], r["company"])
		if pair_key not in child_by_pair:
			child_by_pair[pair_key] = r

	# 5. Build output rows
	rows = []
	for parent_name, comp_info in sliced_pairs:
		comp_name = comp_info["name"]
		existing = child_by_pair.get((parent_name, comp_name))
		row = {
			"name": parent_name,
			"label": parent_name,
			"company": comp_name,
			"is_new": existing is None,
			"company_is_group": comp_info.get("is_group", 0),
			"default_account": existing.get("default_account") if existing else None,
		}
		rows.append(row)

	return {"rows": rows, "total": total}
