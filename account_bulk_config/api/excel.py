"""Excel export and import operations for bulk account configuration."""

import json
from contextlib import suppress

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file

from account_bulk_config.api.batch import CHILD_DOCTYPES, TARGETS
from account_bulk_config.api.company_accounts import get_rows as get_company_rows
from account_bulk_config.api.fields import COMPANY_FIELDS, ITEM_DEFAULT_FIELDS
from account_bulk_config.api.item_defaults import get_rows as get_item_rows
from account_bulk_config.api.mode_of_payment import get_rows as get_mop_rows

COMPANY_EXPORT_FIELDS = [f["fieldname"] for f in COMPANY_FIELDS]
ITEM_EXPORT_FIELDS = [f["fieldname"] for f in ITEM_DEFAULT_FIELDS if not f.get("read_only")]


def _clean_cell(val):
	if val is None:
		return None
	if isinstance(val, float) and val.is_integer():
		val = int(val)
	s = str(val).strip()
	return s if s else None


def _cell(row, idx):
	return row[idx] if idx < len(row) else None


@frappe.whitelist()
def export_sheet(target: str, template: int = 0, **filters) -> None:
	"""Export account configuration rows or template as an Excel (.xlsx) file."""
	if target not in TARGETS:
		frappe.throw(_("Invalid target: {0}").format(target))

	if "filters" in filters and isinstance(filters["filters"], (dict, str)):
		f_arg = filters["filters"]
		if isinstance(f_arg, str):
			with suppress(Exception):
				f_arg = json.loads(f_arg)
		if isinstance(f_arg, dict):
			filters = {**filters, **f_arg}

	is_template = bool(cint(template))

	allowed = [f["fieldname"] for f in TARGETS[target][2] if not f.get("read_only")]
	export_fields = allowed
	if filters.get("fields"):
		wanted = filters["fields"]
		if isinstance(wanted, str):
			wanted = json.loads(wanted) if wanted.startswith("[") else wanted.split(",")
		unknown = [f for f in wanted if f not in allowed]
		if unknown:
			frappe.throw(_("Unknown field(s): {0}").format(", ".join(unknown)))
		export_fields = [f for f in allowed if f in wanted]

	if target == "company":
		headers = ["company"] + export_fields
		data = get_company_rows(
			parent_company=filters.get("parent_company"),
			search=filters.get("search"),
			start=0,
			page_length=0,
		)
		rows = [headers]
		for r in data.get("rows", []):
			if is_template:
				rows.append([r["name"]] + ["" for _ in export_fields])
			else:
				rows.append([r["name"]] + [r.get(f) or "" for f in export_fields])
		filename = f"bulk-company-{'template' if is_template else 'accounts'}"
	elif target == "mode_of_payment":
		headers = ["name", "company"] + export_fields
		data = get_mop_rows(
			mode_of_payment=filters.get("mode_of_payment"),
			parent_company=filters.get("parent_company"),
			company=filters.get("company"),
			start=0,
			page_length=0,
		)
		rows = [headers]
		for r in data.get("rows", []):
			key = [r["name"], r["company"]]
			if is_template:
				rows.append(key + ["" for _ in export_fields])
			else:
				rows.append(key + [r.get(f) or "" for f in export_fields])
		filename = f"bulk-mode_of_payment-{'template' if is_template else 'accounts'}"
	else:
		# item_name is a read-only aid for humans; "name" stays the import key (names are not unique)
		label_cols = ["item_name"] if target == "item" else []
		headers = ["name", *label_cols, "company"] + export_fields
		data = get_item_rows(
			target=target,
			item_group=filters.get("item_group"),
			item=filters.get("item"),
			parent_company=filters.get("parent_company"),
			company=filters.get("company"),
			start=0,
			page_length=0,
		)
		rows = [headers]
		for r in data.get("rows", []):
			key = [r["name"], *([r["label"]] if label_cols else []), r["company"]]
			if is_template:
				rows.append(key + ["" for _ in export_fields])
			else:
				rows.append(key + [r.get(f) or "" for f in export_fields])
		filename = f"bulk-{target}-{'template' if is_template else 'defaults'}"

	build_xlsx_response(rows, filename)


@frappe.whitelist()
def import_sheet(target: str, file_url: str) -> dict:
	"""Parse an uploaded Excel sheet and return diffs against DB as pending changes."""
	if target not in TARGETS:
		frappe.throw(_("Invalid target: {0}").format(target))

	if not file_url:
		frappe.throw(_("Please attach a file"))

	rows = read_xlsx_file_from_attached_file(file_url=file_url)
	if not rows:
		return {"changes": [], "errors": [{"row": 1, "message": _("The file is empty")}]}

	raw_headers = [str(c).strip() if c is not None else "" for c in rows[0]]
	while raw_headers and not raw_headers[-1]:
		raw_headers.pop()

	if not raw_headers:
		return {"changes": [], "errors": [{"row": 1, "message": _("Missing header row")}]}

	allowed_fields = [f["fieldname"] for f in TARGETS[target][2] if not f.get("read_only")]
	if target == "company":
		key_columns = ["company"]
	else:
		key_columns = ["name", "company"]

	# item_name comes from our own export; it is display only and never imported
	valid_columns = set(key_columns) | set(allowed_fields) | ({"item_name"} if target == "item" else set())

	missing_keys = [k for k in key_columns if k not in raw_headers]
	if missing_keys:
		return {
			"changes": [],
			"errors": [{"row": 1, "message": _("Missing required column(s): {0}").format(", ".join(missing_keys))}],
		}

	unknown_cols = [h for h in raw_headers if h not in valid_columns]
	if unknown_cols:
		return {
			"changes": [],
			"errors": [{"row": 1, "message": _("Unknown column(s): {0}").format(", ".join(unknown_cols))}],
		}

	field_indices = {h: idx for idx, h in enumerate(raw_headers) if h in allowed_fields}
	company_idx = raw_headers.index("company")
	name_idx = raw_headers.index("name") if "name" in raw_headers else None

	changes = []
	errors = []
	fields_to_check = list(field_indices.keys())
	parent_doctype = TARGETS[target][0]

	for row_num, row in enumerate(rows[1:], start=2):
		if not row or all(c is None or str(c).strip() == "" for c in row):
			continue

		raw_comp = _cell(row, company_idx)
		comp = str(raw_comp).strip() if raw_comp is not None else ""

		if target == "company":
			if not comp or not frappe.db.exists("Company", comp):
				errors.append({"row": row_num, "message": _("Company {0} does not exist").format(comp or "''")})
				continue

			if not fields_to_check:
				continue

			db_vals = frappe.db.get_value("Company", comp, [*fields_to_check, "is_group"], as_dict=True) or {}
			for field, col_idx in field_indices.items():
				new_val = _clean_cell(_cell(row, col_idx))
				old_val = db_vals.get(field) or None
				if new_val != old_val:
					changes.append({
						"name": comp,
						"company": comp,
						"field": field,
						"old": old_val,
						"new": new_val,
						# lets the page offer propagation to child companies on save
						"company_is_group": cint(db_vals.get("is_group")),
						"is_group": cint(db_vals.get("is_group")),
					})
		else:
			raw_name = _cell(row, name_idx)
			name = str(raw_name).strip() if raw_name is not None else ""

			if not name or not frappe.db.exists(parent_doctype, name):
				errors.append(
					{"row": row_num, "message": _("{0} {1} does not exist").format(parent_doctype, name or "''")}
				)
				continue

			if not comp or not frappe.db.exists("Company", comp):
				errors.append({"row": row_num, "message": _("Company {0} does not exist").format(comp or "''")})
				continue

			if not fields_to_check:
				continue

			existing = (
				frappe.db.get_value(
					CHILD_DOCTYPES[target],
					{"parent": name, "company": comp, "parenttype": parent_doctype},
					fields_to_check,
					as_dict=True,
				)
				or {}
			)

			comp_is_group = cint(frappe.db.get_value("Company", comp, "is_group"))
			for field, col_idx in field_indices.items():
				new_val = _clean_cell(_cell(row, col_idx))
				old_val = existing.get(field) or None
				if new_val != old_val:
					changes.append({
						"name": name,
						"company": comp,
						"field": field,
						"old": old_val,
						"new": new_val,
						"company_is_group": comp_is_group,
					})

	return {"changes": changes, "errors": errors}
