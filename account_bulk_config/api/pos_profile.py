"""API for bulk POS Profile accounts configuration."""

import frappe
from frappe.utils import cint

from account_bulk_config.api.fields import POS_PROFILE_FIELDS

POS_PROFILE_FIELDNAMES = [f["fieldname"] for f in POS_PROFILE_FIELDS]


@frappe.whitelist()
def get_rows(
	pos_profile: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	include_disabled: int = 0,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Return paginated POS Profile rows (one per profile) with their account fields."""
	start = max(0, cint(start))
	page_len = cint(page_length) if page_length is not None else 20

	filters = []
	if pos_profile:
		filters.append(["name", "=", pos_profile])
	if company:
		filters.append(["company", "=", company])
	if not cint(include_disabled):
		filters.append(["disabled", "=", 0])
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

	total = frappe.db.count("POS Profile", filters=filters)
	rows = frappe.get_all(
		"POS Profile",
		filters=filters,
		fields=["name", "company", "disabled", *POS_PROFILE_FIELDNAMES],
		order_by="company asc, name asc",
		start=start,
		limit=page_len,
	)
	for r in rows:
		r["label"] = r["name"]
		# profiles have no children to propagate to
		r["company_is_group"] = 0
	return {"rows": rows, "total": total}


@frappe.whitelist()
def build_fill_changes(
	source_profile: str,
	fields: list[str] | str,
	pos_profile: str | None = None,
	parent_company: str | None = None,
	company: str | None = None,
	include_disabled: int = 0,
) -> dict:
	"""Copy source_profile's values to every filtered profile, mapping company-scoped links by abbr.

	Returns pending changes (not saved) plus values that have no counterpart in the row's company.
	"""
	from account_bulk_config.api.propagation import map_value

	if isinstance(fields, str):
		fields = frappe.parse_json(fields) if fields.startswith("[") else fields.split(",")
	field_map = {f["fieldname"]: f for f in POS_PROFILE_FIELDS}
	unknown = [f for f in fields if f not in field_map]
	if unknown:
		frappe.throw(frappe._("Unknown field(s): {0}").format(", ".join(unknown)))

	src = frappe.db.get_value("POS Profile", source_profile, ["company", *fields], as_dict=True)
	if not src:
		frappe.throw(frappe._("POS Profile {0} does not exist").format(source_profile))

	# an empty source value is not a value to copy (several of these fields are mandatory)
	fields = [f for f in fields if src.get(f)]
	rows = get_rows(pos_profile, parent_company, company, include_disabled, 0, 0)["rows"]
	changes, not_found = [], []
	for r in rows:
		if r["name"] == source_profile:
			continue
		for f in fields:
			new, found = map_value(field_map[f]["link"], src.get(f), src.company, r["company"])
			if not found:
				not_found.append({"name": r["name"], "company": r["company"], "field": f, "value": src.get(f)})
				continue
			old = r.get(f) or None
			if new != old:
				changes.append(
					{"name": r["name"], "company": r["company"], "field": f, "old": old, "new": new, "company_is_group": 0}
				)
	return {"changes": changes, "not_found": not_found}
