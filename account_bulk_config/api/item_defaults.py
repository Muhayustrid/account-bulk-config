"""API for bulk item and item group defaults (Page 2)."""

import frappe
from frappe import _
from frappe.utils import cint

from account_bulk_config.api.fields import ITEM_DEFAULT_FIELDS

ITEM_FIELDNAMES = [f["fieldname"] for f in ITEM_DEFAULT_FIELDS]


@frappe.whitelist()
def get_rows(
	target: str,
	item_group: str | None = None,
	item: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Return paginated (Item/Item Group x Company) pairs with existing item defaults."""
	if target not in ("item", "item_group"):
		frappe.throw(_("Invalid target: {0}").format(target))

	start = max(0, cint(start))
	page_len = cint(page_length) if page_length is not None else 20

	# 1. Determine induk list
	if target == "item":
		item_filters = [["disabled", "=", 0]]
		if item_group:
			ig_info = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
			if not ig_info:
				return {"rows": [], "total": 0}
			ig_descendants = frappe.get_all(
				"Item Group",
				filters=[["lft", ">=", ig_info.lft], ["rgt", "<=", ig_info.rgt]],
				pluck="name",
			)
			item_filters.append(["item_group", "in", ig_descendants])
		if item:
			item_filters.append(["name", "=", item])

		induks = frappe.get_all("Item", filters=item_filters, order_by="name asc", pluck="name")
	else:
		if item_group:
			ig_info = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
			if not ig_info:
				return {"rows": [], "total": 0}
			induks = frappe.get_all(
				"Item Group",
				filters=[["lft", ">=", ig_info.lft], ["rgt", "<=", ig_info.rgt]],
				order_by="lft asc",
				pluck="name",
			)
		else:
			induks = frappe.get_all("Item Group", order_by="lft asc", pluck="name")

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

	if not induks or not companies:
		return {"rows": [], "total": 0}

	num_companies = len(companies)
	total = len(induks) * num_companies

	if start >= total:
		return {"rows": [], "total": total}

	# 3. Slice pairs without materializing full product matrix
	if page_length is not None and page_len == 0:
		end = total
	else:
		end = min(total, start + max(1, page_len))
	sliced_pairs = []
	for idx in range(start, end):
		induk_idx = idx // num_companies
		comp_idx = idx % num_companies
		sliced_pairs.append((induks[induk_idx], companies[comp_idx]))

	# 4. Fetch existing child rows for sliced pairs in one query
	slice_induks = list(dict.fromkeys(p[0] for p in sliced_pairs))
	slice_companies = list(dict.fromkeys(p[1]["name"] for p in sliced_pairs))

	parenttype = "Item" if target == "item" else "Item Group"
	child_rows = frappe.get_all(
		"Item Default",
		filters={
			"parenttype": parenttype,
			"parent": ["in", slice_induks],
			"company": ["in", slice_companies],
		},
		fields=["parent", "company"] + ITEM_FIELDNAMES,
	)

	child_by_pair = {}
	for r in child_rows:
		pair_key = (r["parent"], r["company"])
		if pair_key not in child_by_pair:
			child_by_pair[pair_key] = r

	item_names = (
		dict(frappe.get_all("Item", filters={"name": ["in", slice_induks]}, fields=["name", "item_name"], as_list=True))
		if target == "item"
		else {}
	)

	# 5. Build output rows
	rows = []
	for induk_name, comp_info in sliced_pairs:
		comp_name = comp_info["name"]
		existing = child_by_pair.get((induk_name, comp_name))
		row = {
			"name": induk_name,
			"label": item_names.get(induk_name) or induk_name,
			"company": comp_name,
			"is_new": existing is None,
			"company_is_group": comp_info.get("is_group", 0),
		}
		for f in ITEM_FIELDNAMES:
			row[f] = existing.get(f) if existing else None
		rows.append(row)

	return {"rows": rows, "total": total}
