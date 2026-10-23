"""API for bulk Warehouse accounts configuration."""

import frappe
from frappe.utils import cint

from account_bulk_config.api.fields import WAREHOUSE_FIELDS
from account_bulk_config.api.propagation import _swap_abbr

WAREHOUSE_FIELDNAMES = [f["fieldname"] for f in WAREHOUSE_FIELDS]


@frappe.whitelist()
def get_rows(
	warehouse: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	include_disabled: int = 0,
	include_group: int = 0,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Return paginated Warehouse rows with their account fields."""
	start = max(0, cint(start))
	page_len = cint(page_length) if page_length is not None else 20

	filters = []
	if warehouse:
		filters.append(["name", "=", warehouse])
	if company:
		filters.append(["company", "=", company])
	if not cint(include_disabled):
		filters.append(["disabled", "=", 0])
	if not cint(include_group):
		filters.append(["is_group", "=", 0])
	if parent_company:
		parent_info = frappe.db.get_value("Company", parent_company, ["lft", "rgt"], as_dict=True)
		if not parent_info:
			return {"rows": [], "total": 0}
		subtree = frappe.get_all(
			"Company",
			filters={"lft": [">=", parent_info.lft], "rgt": ["<=", parent_info.rgt]},
			pluck="name",
		)
		filters.append(["company", "in", subtree])

	total = frappe.db.count("Warehouse", filters=filters)
	rows = frappe.get_all(
		"Warehouse",
		filters=filters,
		fields=["name", "company", "disabled", "is_group", *WAREHOUSE_FIELDNAMES],
		order_by="company asc, lft asc",
		start=start,
		limit=page_len,
	)
	for r in rows:
		r["label"] = r["name"]
		# warehouses belong to one company, no propagation needed
		r["company_is_group"] = 0
	return {"rows": rows, "total": total}


@frappe.whitelist()
def build_fill_changes(
	source_warehouse: str,
	fields: list[str] | str,
	warehouse: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	include_disabled: int = 0,
	include_group: int = 0,
) -> dict:
	"""Copy source_warehouse's values to every filtered warehouse, mapping company-scoped links by abbr.

	Returns pending changes (not saved) plus values that have no counterpart in the row's company.
	"""
	if isinstance(fields, str):
		fields = frappe.parse_json(fields) if fields.startswith("[") else fields.split(",")
	field_map = {f["fieldname"]: f for f in WAREHOUSE_FIELDS}
	unknown = [f for f in fields if f not in field_map]
	if unknown:
		frappe.throw(frappe._("Unknown field(s): {0}").format(", ".join(unknown)))

	src = frappe.db.get_value("Warehouse", source_warehouse, ["company", *fields], as_dict=True)
	if not src:
		frappe.throw(frappe._("Warehouse {0} does not exist").format(source_warehouse))

	fields = [f for f in fields if src.get(f)]
	if not fields:
		return {"changes": [], "not_found": []}

	rows = get_rows(
		warehouse=warehouse,
		parent_company=parent_company,
		company=company,
		include_disabled=include_disabled,
		include_group=include_group,
		start=0,
		page_length=0,
	)["rows"]

	target_rows = [r for r in rows if r["name"] != source_warehouse]
	if not target_rows:
		return {"changes": [], "not_found": []}

	companies = list({src.company, *(r["company"] for r in target_rows)})
	abbr_map = dict(
		frappe.get_all(
			"Company",
			filters={"name": ["in", companies]},
			fields=["name", "abbr"],
			as_list=True,
		)
	)
	src_abbr = abbr_map.get(src.company)

	candidate_names = set()
	for r in target_rows:
		dst_abbr = abbr_map.get(r["company"])
		for f in fields:
			val = src.get(f)
			mapped = _swap_abbr(val, src_abbr, dst_abbr)
			if mapped:
				candidate_names.add(mapped)

	valid_accounts = set()
	if candidate_names:
		valid_accounts = {
			(a["name"], a["company"])
			for a in frappe.get_all(
				"Account",
				filters={"name": ["in", list(candidate_names)]},
				fields=["name", "company"],
			)
		}

	changes, not_found = [], []
	for r in target_rows:
		row_company = r["company"]
		row_abbr = abbr_map.get(row_company)
		for f in fields:
			src_val = src.get(f)
			mapped = _swap_abbr(src_val, src_abbr, row_abbr)
			if not mapped or (mapped, row_company) not in valid_accounts:
				not_found.append({"name": r["name"], "company": row_company, "field": f, "value": src_val})
				continue
			old = r.get(f) or None
			if mapped != old:
				changes.append(
					{"name": r["name"], "company": row_company, "field": f, "old": old, "new": mapped, "company_is_group": 0}
				)
	return {"changes": changes, "not_found": not_found}
