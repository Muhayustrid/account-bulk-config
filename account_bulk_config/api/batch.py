"""Batch save operations and background job processing for bulk account configuration."""

import json
import uuid
from contextlib import suppress

import frappe
from frappe import _

from account_bulk_config.api.fields import COMPANY_FIELDS, ITEM_DEFAULT_FIELDS, MOP_FIELDS, validate_link

TARGETS = {
	"company": ("Company", None, COMPANY_FIELDS),
	"item": ("Item", "item_defaults", ITEM_DEFAULT_FIELDS),
	"item_group": ("Item Group", "item_group_defaults", ITEM_DEFAULT_FIELDS),
	"mode_of_payment": ("Mode of Payment", "accounts", MOP_FIELDS),
}

CHILD_DOCTYPES = {
	"item": "Item Default",
	"item_group": "Item Default",
	"mode_of_payment": "Mode of Payment Account",
}


def _extract_error_message(exc: Exception) -> str:
	messages = frappe.get_message_log()
	if messages:
		msg = messages[-1]
		frappe.clear_last_message()
		if isinstance(msg, dict):
			return msg.get("message") or str(exc)
		if isinstance(msg, str):
			with suppress(json.JSONDecodeError):
				data = json.loads(msg)
				if isinstance(data, dict):
					return data.get("message") or msg
			return msg
	return str(exc)


@frappe.whitelist()
def save_changes(target: str, changes: list[dict] | str) -> dict:
	"""Save changes synchronously if <= 20 documents, or enqueue long job if > 20."""
	if target not in TARGETS:
		frappe.throw(_("Invalid target: {0}").format(target))

	if isinstance(changes, str):
		changes = json.loads(changes)

	doc_names = list(dict.fromkeys(c.get("name") for c in changes if c.get("name")))
	if len(doc_names) <= 20:
		return {"results": apply_changes(target, changes)}

	job_id = f"bac_{uuid.uuid4().hex[:12]}"
	frappe.enqueue(
		"account_bulk_config.api.batch.run_job",
		queue="long",
		job_id=job_id,
		bac_job_id=job_id,
		target=target,
		changes=changes,
		user=frappe.session.user,
	)
	return {"job_id": job_id}


def run_job(
	target: str,
	changes: list[dict],
	user: str,
	job_id: str | None = None,
	bac_job_id: str | None = None,
) -> None:
	"""Background worker job to apply changes and publish realtime progress and completion."""
	effective_job_id = bac_job_id or job_id

	def _progress(name, count, total_docs):
		percent = int((count / total_docs) * 100)
		frappe.publish_progress(percent, title=_("Saving"), description=name)

	results = apply_changes(target, changes, progress_callback=_progress)
	frappe.publish_realtime(
		"bulk_account_config_done",
		{"job_id": effective_job_id, "results": results},
		user=user,
	)


def apply_changes(target: str, changes: list[dict], progress_callback=None) -> list[dict]:
	"""Apply changes grouped by parent document with savepoint isolation per document."""
	if target not in TARGETS:
		frappe.throw(_("Invalid target: {0}").format(target))

	doctype, child_table_field, field_defs = TARGETS[target]
	valid_field_map = {f["fieldname"]: f for f in field_defs}

	ordered_pairs = []
	seen_pairs = set()
	changes_by_doc = {}
	companies_by_doc = {}

	for c in changes:
		doc_name = c.get("name")
		comp = c.get("company")
		pair = (doc_name, comp)
		if pair not in seen_pairs:
			seen_pairs.add(pair)
			ordered_pairs.append(pair)

		if doc_name not in changes_by_doc:
			changes_by_doc[doc_name] = []
			companies_by_doc[doc_name] = []
		changes_by_doc[doc_name].append(c)
		if comp not in companies_by_doc[doc_name]:
			companies_by_doc[doc_name].append(comp)

	results = {}
	total_docs = len(changes_by_doc)

	for doc_idx, (doc_name, doc_changes) in enumerate(changes_by_doc.items()):
		doc_companies = companies_by_doc[doc_name]

		# 1. Check for unknown fields
		unknown_field = None
		for c in doc_changes:
			f = c.get("field")
			if f not in valid_field_map:
				unknown_field = f
				break

		if unknown_field:
			for comp in doc_companies:
				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "error",
					"message": _("Unknown field: {0}").format(unknown_field),
					"values": {},
				}
			if progress_callback:
				progress_callback(doc_name, doc_idx + 1, total_docs)
			continue

		# 2. Check document existence
		if not frappe.db.exists(doctype, doc_name):
			for comp in doc_companies:
				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "error",
					"message": _("{0} {1} does not exist").format(doctype, doc_name),
					"values": {},
				}
			if progress_callback:
				progress_callback(doc_name, doc_idx + 1, total_docs)
			continue

		doc = frappe.get_doc(doctype, doc_name)

		# 3. Check write permission
		if not frappe.has_permission(doctype, "write", doc=doc):
			for comp in doc_companies:
				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "error",
					"message": _("No write permission for {0} {1}").format(doctype, doc_name),
					"values": {},
				}
			if progress_callback:
				progress_callback(doc_name, doc_idx + 1, total_docs)
			continue

		# 4. Check stale old values and validate new values
		companies_to_apply = []
		comp_changes = {}
		for c in doc_changes:
			comp = c.get("company")
			comp_changes.setdefault(comp, []).append(c)

		validation_error = None

		for comp in doc_companies:
			if target == "company":
				row = doc
			else:
				row = next((r for r in (doc.get(child_table_field) or []) if r.company == comp), None)

			is_stale = False
			for c in comp_changes[comp]:
				curr_val = getattr(row, c["field"], None) if row else None
				old_norm = c.get("old") or None
				curr_norm = curr_val or None
				if old_norm != curr_norm:
					is_stale = True
					break

			if is_stale:
				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "skipped",
					"message": _("Changed by someone else"),
					"values": {},
				}
				continue

			# Validate links for non-stale company
			for c in comp_changes[comp]:
				new_val = c.get("new") or None
				err = validate_link(valid_field_map[c["field"]], new_val, comp)
				if err:
					validation_error = err
					break

			if validation_error:
				break

			companies_to_apply.append(comp)

		if validation_error:
			for comp in doc_companies:
				if (doc_name, comp) not in results:
					results[(doc_name, comp)] = {
						"name": doc_name,
						"company": comp,
						"status": "error",
						"message": validation_error,
						"values": {},
					}
			if progress_callback:
				progress_callback(doc_name, doc_idx + 1, total_docs)
			continue

		if not companies_to_apply:
			if progress_callback:
				progress_callback(doc_name, doc_idx + 1, total_docs)
			continue

		# 5. Apply changes with savepoint
		sp = f"sp_{uuid.uuid4().hex[:8]}"
		frappe.db.savepoint(sp)
		try:
			for comp in companies_to_apply:
				if target == "company":
					row = doc
				else:
					row = next((r for r in (doc.get(child_table_field) or []) if r.company == comp), None)
					if target == "mode_of_payment":
						# Mode of Payment Account requires default_account matching company.
						# ERPNext validation rejects empty account rows, so remove if empty.
						new_acc = next(
							(
								c.get("new") or None
								for c in comp_changes[comp]
								if c["field"] == "default_account"
							),
							getattr(row, "default_account", None) if row else None,
						)
						if not new_acc:
							if row:
								doc.remove(row)
							continue
					if not row:
						row = doc.append(child_table_field, {"company": comp})

				for c in comp_changes[comp]:
					row.set(c["field"], c.get("new") or None)

			doc.save(ignore_version=False)
			doc.reload()
			frappe.db.release_savepoint(sp)

			for comp in companies_to_apply:
				if target == "company":
					saved_row = doc
				else:
					saved_row = next(
						(r for r in (doc.get(child_table_field) or []) if r.company == comp), None
					)

				vals = {}
				for c in comp_changes[comp]:
					f = c["field"]
					vals[f] = getattr(saved_row, f, None) if saved_row else None

				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "ok",
					"message": "",
					"values": vals,
				}
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback(save_point=sp)
			err_msg = _extract_error_message(e)
			for comp in companies_to_apply:
				results[(doc_name, comp)] = {
					"name": doc_name,
					"company": comp,
					"status": "error",
					"message": err_msg,
					"values": {},
				}

		if progress_callback:
			progress_callback(doc_name, doc_idx + 1, total_docs)

	return [results[pair] for pair in ordered_pairs]
