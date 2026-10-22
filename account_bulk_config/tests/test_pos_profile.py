"""Tests for bulk POS Profile account configuration."""

from io import BytesIO

import frappe
import openpyxl
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from account_bulk_config.api.batch import apply_changes
from account_bulk_config.api.excel import export_sheet, import_sheet
from account_bulk_config.api.pos_profile import build_fill_changes, get_rows
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	PARENT,
	POS_A1,
	POS_A2,
	POS_B,
	acct,
	setup_pos_profiles,
)


def _chg(name, field, new):
	company, old = frappe.db.get_value("POS Profile", name, ["company", field])
	return {"name": name, "company": company, "field": field, "old": old, "new": new}


class TestPOSProfile(IntegrationTestCase):
	def setUp(self):
		setup_pos_profiles()

	def test_get_rows_one_row_per_profile(self):
		out = get_rows(parent_company=PARENT)
		names = [r["name"] for r in out["rows"]]
		self.assertEqual(out["total"], 3)
		self.assertEqual(sorted(names), sorted([POS_A1, POS_A2, POS_B]))
		self.assertEqual(get_rows(company=CHILD_A)["total"], 2)

		frappe.db.set_value("POS Profile", POS_A2, "disabled", 1)
		try:
			self.assertEqual(get_rows(company=CHILD_A)["total"], 1)
			self.assertEqual(get_rows(company=CHILD_A, include_disabled=1)["total"], 2)
		finally:
			frappe.db.set_value("POS Profile", POS_A2, "disabled", 0)

	def test_save_updates_only_that_profile(self):
		cash_a = acct("Cash", CHILD_A)
		res = apply_changes("pos_profile", [_chg(POS_A1, "account_for_change_amount", cash_a)])
		self.assertEqual(res[0]["status"], "ok", res[0]["message"])
		self.assertEqual(frappe.db.get_value("POS Profile", POS_A1, "account_for_change_amount"), cash_a)
		self.assertIsNone(frappe.db.get_value("POS Profile", POS_A2, "account_for_change_amount"))

	def test_account_of_another_company_rejected(self):
		res = apply_changes("pos_profile", [_chg(POS_A1, "account_for_change_amount", acct("Cash", CHILD_B))])
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("belongs to", res[0]["message"])

	def test_wrong_company_key_rejected(self):
		chg = _chg(POS_A1, "account_for_change_amount", acct("Cash", CHILD_B))
		chg["company"] = CHILD_B
		res = apply_changes("pos_profile", [chg])
		self.assertEqual(res[0]["status"], "error")
		self.assertIsNone(frappe.db.get_value("POS Profile", POS_A1, "account_for_change_amount"))

	def test_fill_maps_values_per_company(self):
		frappe.db.set_value("POS Profile", POS_A1, "account_for_change_amount", acct("Cash", CHILD_A))
		out = build_fill_changes(POS_A1, ["account_for_change_amount", "cost_center"], parent_company=PARENT)
		by = {c["name"]: c for c in out["changes"]}
		# empty source field (cost_center) is skipped, source row itself is skipped
		self.assertEqual(set(by), {POS_A2, POS_B})
		self.assertEqual(by[POS_A2]["new"], acct("Cash", CHILD_A))
		self.assertEqual(by[POS_B]["new"], acct("Cash", CHILD_B))
		self.assertEqual(out["not_found"], [])
		# nothing is written until the changes are saved
		self.assertIsNone(frappe.db.get_value("POS Profile", POS_B, "account_for_change_amount"))

	def test_export_and_import(self):
		frappe.local.response = frappe._dict()
		export_sheet("pos_profile", parent_company=PARENT, fields="account_for_change_amount")
		wb = openpyxl.load_workbook(BytesIO(frappe.response["filecontent"]))
		rows = [[c.value for c in r] for r in wb.active.iter_rows()]
		self.assertEqual(rows[0], ["name", "company", "account_for_change_amount"])
		self.assertEqual(len(rows), 4)

		content = make_xlsx(
			[
				["name", "company", "account_for_change_amount"],
				[POS_B, CHILD_B, acct("Cash", CHILD_B)],
				[POS_A1, CHILD_B, acct("Cash", CHILD_B)],
			],
			"Sheet1",
		).getvalue()
		f = frappe.get_doc(
			{"doctype": "File", "file_name": "bac_pos.xlsx", "content": content, "is_private": 1}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", f.name, ignore_permissions=True))
		out = import_sheet("pos_profile", f.file_url)
		self.assertEqual([(c["name"], c["company_is_group"]) for c in out["changes"]], [(POS_B, 0)])
		self.assertEqual(out["errors"][0]["row"], 3)
