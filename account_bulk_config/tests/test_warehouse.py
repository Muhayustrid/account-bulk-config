"""Tests for bulk Warehouse account configuration."""

from io import BytesIO

import frappe
import openpyxl
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from account_bulk_config.api.batch import apply_changes
from account_bulk_config.api.excel import export_sheet, import_sheet
from account_bulk_config.api.fields import WAREHOUSE_FIELDS, get_field_meta
from account_bulk_config.api.warehouse import build_fill_changes, get_rows
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	PARENT,
	WH_A1,
	WH_A2,
	WH_B,
	acct,
	setup_warehouses,
)


def _chg(name, field, new):
	company, old = frappe.db.get_value("Warehouse", name, ["company", field])
	return {"name": name, "company": company, "field": field, "old": old, "new": new}


class TestWarehouse(IntegrationTestCase):
	def setUp(self):
		setup_warehouses()

	def test_get_rows_filters(self):
		out = get_rows(parent_company=PARENT)
		names = [r["name"] for r in out["rows"]]
		self.assertIn(WH_A1, names)
		self.assertIn(WH_A2, names)
		self.assertIn(WH_B, names)

		# By company: default exclude group
		out_a = get_rows(company=CHILD_A)
		self.assertNotIn("All Warehouses - BACPA", [r["name"] for r in out_a["rows"]])
		self.assertEqual(out_a["total"], 4)

		# include_group=1 includes group warehouses
		out_a_grp = get_rows(company=CHILD_A, include_group=1)
		self.assertIn("All Warehouses - BACPA", [r["name"] for r in out_a_grp["rows"]])
		self.assertEqual(out_a_grp["total"], 5)

		# include_disabled filter
		frappe.db.set_value("Warehouse", WH_A2, "disabled", 1)
		try:
			self.assertEqual(get_rows(company=CHILD_A)["total"], 3)
			self.assertEqual(get_rows(company=CHILD_A, include_disabled=1)["total"], 4)
		finally:
			frappe.db.set_value("Warehouse", WH_A2, "disabled", 0)

		# single warehouse filter
		out_single = get_rows(warehouse=WH_A1)
		self.assertEqual(out_single["total"], 1)
		self.assertEqual(out_single["rows"][0]["name"], WH_A1)
		self.assertEqual(out_single["rows"][0]["company_is_group"], 0)
		self.assertEqual(out_single["rows"][0]["label"], WH_A1)

	def test_save_updates_only_that_warehouse(self):
		stock_a = acct("Stock In Hand", CHILD_A)
		res = apply_changes("warehouse", [_chg(WH_A1, "account", stock_a)])
		self.assertEqual(res[0]["status"], "ok", res[0]["message"])
		self.assertEqual(frappe.db.get_value("Warehouse", WH_A1, "account"), stock_a)
		self.assertIsNone(frappe.db.get_value("Warehouse", WH_A2, "account"))

	def test_account_of_another_company_rejected(self):
		res = apply_changes("warehouse", [_chg(WH_A1, "account", acct("Stock In Hand", CHILD_B))])
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("belongs to", res[0]["message"])

	def test_non_stock_account_rejected(self):
		res = apply_changes("warehouse", [_chg(WH_A1, "account", acct("Cash", CHILD_A))])
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("account_type", res[0]["message"])

	def test_wrong_company_key_rejected(self):
		chg = _chg(WH_A1, "account", acct("Stock In Hand", CHILD_B))
		chg["company"] = CHILD_B
		res = apply_changes("warehouse", [chg])
		self.assertEqual(res[0]["status"], "error")
		self.assertIn("belongs to", res[0]["message"])
		self.assertIsNone(frappe.db.get_value("Warehouse", WH_A1, "account"))

	def test_fill_maps_account_per_company(self):
		frappe.db.set_value("Warehouse", WH_A1, "account", acct("Stock In Hand", CHILD_A))
		out = build_fill_changes(WH_A1, ["account"], parent_company=PARENT)
		by = {c["name"]: c for c in out["changes"]}
		self.assertIn(WH_A2, by)
		self.assertIn(WH_B, by)
		self.assertNotIn(WH_A1, by)
		self.assertEqual(by[WH_A2]["new"], acct("Stock In Hand", CHILD_A))
		self.assertEqual(by[WH_B]["new"], acct("Stock In Hand", CHILD_B))
		self.assertEqual(out["not_found"], [])
		self.assertIsNone(frappe.db.get_value("Warehouse", WH_B, "account"))

	def test_fill_reports_not_found(self):
		frappe.db.set_value("Warehouse", WH_A1, "account", "Ghost Stock - BACPA")
		out = build_fill_changes(WH_A1, ["account"], parent_company=PARENT)
		not_found_names = [nf["name"] for nf in out["not_found"]]
		self.assertIn(WH_B, not_found_names)

	def test_export_and_import(self):
		frappe.local.response = frappe._dict()
		export_sheet("warehouse", parent_company=PARENT, fields="account")
		wb = openpyxl.load_workbook(BytesIO(frappe.response["filecontent"]))
		rows = [[c.value for c in r] for r in wb.active.iter_rows()]
		self.assertEqual(rows[0], ["name", "company", "account"])

		content = make_xlsx(
			[
				["name", "company", "account"],
				[WH_B, CHILD_B, acct("Stock In Hand", CHILD_B)],
				[WH_A1, CHILD_B, acct("Stock In Hand", CHILD_B)],
			],
			"Sheet1",
		).getvalue()
		f = frappe.get_doc(
			{"doctype": "File", "file_name": "bac_wh.xlsx", "content": content, "is_private": 1}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", f.name, ignore_permissions=True))
		out = import_sheet("warehouse", f.file_url)
		self.assertEqual([(c["name"], c["company_is_group"]) for c in out["changes"]], [(WH_B, 0)])
		self.assertEqual(out["errors"][0]["row"], 3)

	def test_field_meta(self):
		meta = get_field_meta("warehouse")
		self.assertEqual(meta, WAREHOUSE_FIELDS)
