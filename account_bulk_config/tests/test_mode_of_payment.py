"""Tests for Mode of Payment bulk account configuration."""

from io import BytesIO

import frappe
import openpyxl
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from account_bulk_config.api.batch import apply_changes
from account_bulk_config.api.excel import export_sheet, import_sheet
from account_bulk_config.api.fields import MOP_FIELDS, get_field_meta
from account_bulk_config.api.mode_of_payment import get_rows
from account_bulk_config.api.propagation import preview_propagation
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	MOP_1,
	PARENT,
	acct,
	setup_world,
)

ADMIN = "Administrator"


class TestModeOfPayment(IntegrationTestCase):
	def setUp(self):
		setup_world()
		frappe.db.delete("Mode of Payment Account", {"parent": MOP_1})

	def _sheet(self, rows):
		content = make_xlsx(rows, "Sheet1").getvalue()
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"test_{frappe.generate_hash(length=8)}.xlsx",
				"attached_to_doctype": "User",
				"attached_to_name": ADMIN,
				"content": content,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", file_doc.name, ignore_permissions=True))
		return file_doc.file_url

	def _read_export_rows(self):
		content = frappe.response.get("filecontent")
		wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
		ws = wb.active
		return [[cell.value for cell in row] for row in ws.iter_rows()]

	def test_field_meta(self):
		meta = get_field_meta("mode_of_payment")
		self.assertEqual(meta, MOP_FIELDS)
		self.assertEqual(len(meta), 1)
		self.assertEqual(meta[0]["fieldname"], "default_account")
		self.assertEqual(meta[0]["link"], "Account")
		self.assertEqual(meta[0]["filters"], {"account_type": ["in", ["Bank", "Cash", "Receivable"]]})

	def test_get_rows_rows_total_is_new_and_filters(self):
		out = get_rows(mode_of_payment=MOP_1, parent_company=PARENT)
		self.assertEqual(out["total"], 3)
		self.assertEqual(len(out["rows"]), 3)
		self.assertEqual(out["rows"][0]["name"], MOP_1)
		self.assertEqual(out["rows"][0]["label"], MOP_1)
		self.assertTrue(out["rows"][0]["is_new"])
		self.assertIsNone(out["rows"][0]["default_account"])

		out_filtered = get_rows(mode_of_payment=MOP_1, company=CHILD_A)
		self.assertEqual(out_filtered["total"], 1)
		self.assertEqual(len(out_filtered["rows"]), 1)
		self.assertEqual(out_filtered["rows"][0]["company"], CHILD_A)

		out_paged = get_rows(mode_of_payment=MOP_1, parent_company=PARENT, start=0, page_length=2)
		self.assertEqual(out_paged["total"], 3)
		self.assertEqual(len(out_paged["rows"]), 2)

		out_all = get_rows(mode_of_payment=MOP_1, parent_company=PARENT, page_length=0)
		self.assertEqual(len(out_all["rows"]), out_all["total"])

		# Disabled mode of payment is excluded
		frappe.db.set_value("Mode of Payment", MOP_1, "enabled", 0)
		try:
			out_disabled = get_rows(mode_of_payment=MOP_1, parent_company=PARENT)
			self.assertEqual(out_disabled["total"], 0)
			self.assertEqual(out_disabled["rows"], [])
		finally:
			frappe.db.set_value("Mode of Payment", MOP_1, "enabled", 1)

	def test_save_creates_new_accounts_row(self):
		cash_a = acct("Cash", CHILD_A)
		res = apply_changes(
			"mode_of_payment",
			[
				{
					"name": MOP_1,
					"company": CHILD_A,
					"field": "default_account",
					"old": None,
					"new": cash_a,
				}
			],
		)
		self.assertEqual(res[0]["status"], "ok")
		self.assertEqual(res[0]["values"]["default_account"], cash_a)

		db_val = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": MOP_1, "company": CHILD_A},
			"default_account",
		)
		self.assertEqual(db_val, cash_a)

		rows = get_rows(mode_of_payment=MOP_1, company=CHILD_A)["rows"]
		self.assertFalse(rows[0]["is_new"])
		self.assertEqual(rows[0]["default_account"], cash_a)

	def test_setting_existing_row_to_empty_removes_row_and_saves(self):
		cash_a = acct("Cash", CHILD_A)
		apply_changes(
			"mode_of_payment",
			[
				{
					"name": MOP_1,
					"company": CHILD_A,
					"field": "default_account",
					"old": None,
					"new": cash_a,
				}
			],
		)
		self.assertTrue(frappe.db.exists("Mode of Payment Account", {"parent": MOP_1, "company": CHILD_A}))

		res = apply_changes(
			"mode_of_payment",
			[
				{
					"name": MOP_1,
					"company": CHILD_A,
					"field": "default_account",
					"old": cash_a,
					"new": None,
				}
			],
		)
		self.assertEqual(res[0]["status"], "ok")
		self.assertIsNone(res[0]["values"]["default_account"])
		self.assertFalse(frappe.db.exists("Mode of Payment Account", {"parent": MOP_1, "company": CHILD_A}))

	def test_account_of_another_company_error(self):
		cash_b = acct("Cash", CHILD_B)
		res = apply_changes(
			"mode_of_payment",
			[
				{
					"name": MOP_1,
					"company": CHILD_A,
					"field": "default_account",
					"old": None,
					"new": cash_b,
				}
			],
		)
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("belongs to", res[0]["message"])

	def test_account_with_wrong_account_type_error(self):
		sales_a = acct("Sales", CHILD_A)
		res = apply_changes(
			"mode_of_payment",
			[
				{
					"name": MOP_1,
					"company": CHILD_A,
					"field": "default_account",
					"old": None,
					"new": sales_a,
				}
			],
		)
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("account_type", res[0]["message"])

	def test_preview_propagation(self):
		cash_p = acct("Cash", PARENT)
		chg = {
			"name": MOP_1,
			"company": PARENT,
			"field": "default_account",
			"old": None,
			"new": cash_p,
		}
		rows = {r["company"]: r for r in preview_propagation("mode_of_payment", [chg])}
		self.assertIn(CHILD_A, rows)
		self.assertIn(CHILD_B, rows)
		self.assertEqual(rows[CHILD_A]["status"], "changed")
		self.assertTrue(rows[CHILD_A]["checked"])
		self.assertEqual(rows[CHILD_A]["new"], acct("Cash", CHILD_A))
		self.assertEqual(rows[CHILD_B]["new"], acct("Cash", CHILD_B))

	def test_export_and_import_sheet(self):
		frappe.local.response = frappe._dict()
		export_sheet("mode_of_payment", template=0, parent_company=PARENT, mode_of_payment=MOP_1)
		self.assertEqual(frappe.response["type"], "binary")
		rows = self._read_export_rows()
		self.assertEqual(rows[0], ["name", "company", "default_account"])

		cash_a = acct("Cash", CHILD_A)
		url = self._sheet([
			["name", "company", "default_account"],
			[MOP_1, CHILD_A, cash_a],
		])
		out = import_sheet("mode_of_payment", url)
		self.assertEqual(out["errors"], [])
		self.assertEqual(len(out["changes"]), 1)
		self.assertEqual(out["changes"][0]["name"], MOP_1)
		self.assertEqual(out["changes"][0]["company"], CHILD_A)
		self.assertEqual(out["changes"][0]["field"], "default_account")
		self.assertEqual(out["changes"][0]["new"], cash_a)
		self.assertEqual(out["changes"][0]["company_is_group"], 0)
