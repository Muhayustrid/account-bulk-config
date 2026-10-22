"""Tests for Excel export and import operations (account_bulk_config.api.excel)."""

from io import BytesIO

import frappe
import openpyxl
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from account_bulk_config.api.excel import (
	COMPANY_EXPORT_FIELDS,
	ITEM_EXPORT_FIELDS,
	export_sheet,
	import_sheet,
)
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	ITEM_1,
	ITEM_GROUP,
	PARENT,
	acct,
	setup_world,
)

ADMIN = "Administrator"


class TestExcel(IntegrationTestCase):
	def setUp(self):
		setup_world()

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

	def test_import_returns_changes_only_for_diffs(self):
		sheet = self._sheet
		cur = frappe.db.get_value("Company", CHILD_A, "default_income_account")
		url = sheet([["company", "default_income_account"], [CHILD_A, cur], [CHILD_B, acct("Service", CHILD_B)]])
		out = import_sheet("company", url)
		self.assertEqual([(c["company"], c["new"]) for c in out["changes"]], [(CHILD_B, acct("Service", CHILD_B))])
		self.assertEqual(
			frappe.db.get_value("Company", CHILD_B, "default_income_account") != acct("Service", CHILD_B),
			True,
		)

	def test_import_blank_and_unknown(self):
		sheet = self._sheet
		sales_a = acct("Sales", CHILD_A)
		frappe.db.set_value("Company", CHILD_A, "default_income_account", sales_a)

		url = sheet([
			["company", "default_income_account"],
			[CHILD_A, ""],
			["Nope Co", sales_a],
		])
		out = import_sheet("company", url)
		self.assertEqual(len(out["changes"]), 1)
		self.assertEqual(out["changes"][0]["company"], CHILD_A)
		self.assertEqual(out["changes"][0]["old"], sales_a)
		self.assertIsNone(out["changes"][0]["new"])

		self.assertEqual(len(out["errors"]), 1)
		self.assertEqual(out["errors"][0]["row"], 3)
		self.assertIn("Nope Co", out["errors"][0]["message"])

	def test_import_bad_header(self):
		sheet = self._sheet
		url = sheet([["company", "abbr"], [CHILD_A, "BACPA"]])
		out = import_sheet("company", url)
		self.assertEqual(out["changes"], [])
		self.assertEqual(out["errors"][0]["row"], 1)
		self.assertIn("abbr", out["errors"][0]["message"])

	def test_import_missing_key_column(self):
		sheet = self._sheet
		url = sheet([["default_income_account"], [acct("Sales", CHILD_A)]])
		out = import_sheet("company", url)
		self.assertEqual(out["changes"], [])
		self.assertEqual(out["errors"][0]["row"], 1)
		self.assertIn("company", out["errors"][0]["message"])

	def test_import_item_defaults(self):
		sheet = self._sheet
		sales_a = acct("Sales", CHILD_A)
		url = sheet([
			["name", "company", "income_account"],
			[ITEM_1, CHILD_A, sales_a],
			["Ghost Item", CHILD_A, sales_a],
			[ITEM_1, "Ghost Co", sales_a],
		])
		out = import_sheet("item", url)
		self.assertEqual(len(out["changes"]), 1)
		self.assertEqual(out["changes"][0]["name"], ITEM_1)
		self.assertEqual(out["changes"][0]["company"], CHILD_A)
		self.assertEqual(out["changes"][0]["new"], sales_a)

		self.assertEqual(len(out["errors"]), 2)
		self.assertEqual(out["errors"][0]["row"], 3)
		self.assertIn("Ghost Item", out["errors"][0]["message"])
		self.assertEqual(out["errors"][1]["row"], 4)
		self.assertIn("Ghost Co", out["errors"][1]["message"])

	def test_export_company_and_template(self):
		frappe.local.response = frappe._dict()
		export_sheet("company", template=0, parent_company=PARENT)
		self.assertEqual(frappe.response["type"], "binary")
		rows = self._read_export_rows()
		self.assertEqual(rows[0][0], "company")
		self.assertEqual(len(rows[0]), len(COMPANY_EXPORT_FIELDS) + 1)
		self.assertEqual(len(rows), 4)  # header + 3 companies

		frappe.local.response = frappe._dict()
		export_sheet("company", template=1, parent_company=PARENT)
		rows = self._read_export_rows()
		self.assertEqual(rows[0][0], "company")
		# Key column filled, account columns empty
		for r in rows[1:]:
			self.assertIsNotNone(r[0])
			for cell in r[1:]:
				self.assertIn(cell, (None, ""))

	def test_export_item_and_template(self):
		frappe.local.response = frappe._dict()
		export_sheet("item", template=0, item_group=ITEM_GROUP, parent_company=PARENT)
		self.assertEqual(frappe.response["type"], "binary")
		rows = self._read_export_rows()
		self.assertEqual(rows[0][:3], ["name", "item_name", "company"])
		self.assertEqual(len(rows[0]), len(ITEM_EXPORT_FIELDS) + 3)
		self.assertEqual(len(rows), 7)  # header + 2 items * 3 companies = 6 data rows
		self.assertEqual(rows[1][:2], [ITEM_1, frappe.db.get_value("Item", ITEM_1, "item_name")])

		frappe.local.response = frappe._dict()
		export_sheet("item", template=1, item_group=ITEM_GROUP, parent_company=PARENT)
		rows = self._read_export_rows()
		for r in rows[1:]:
			self.assertIsNotNone(r[0])
			self.assertIsNotNone(r[1])
			self.assertIsNotNone(r[2])
			for cell in r[3:]:
				self.assertIn(cell, (None, ""))

		frappe.local.response = frappe._dict()
		export_sheet("item_group", template=0, item_group=ITEM_GROUP, parent_company=PARENT)
		self.assertEqual(self._read_export_rows()[0][:2], ["name", "company"])

	def test_import_ignores_item_name_column(self):
		sales_a = acct("Sales", CHILD_A)
		url = self._sheet([
			["name", "item_name", "company", "income_account"],
			[ITEM_1, "any label", CHILD_A, sales_a],
		])
		out = import_sheet("item", url)
		self.assertEqual(out["errors"], [])
		self.assertEqual([(c["name"], c["field"], c["new"]) for c in out["changes"]], [(ITEM_1, "income_account", sales_a)])

	def test_import_flags_group_company(self):
		url = self._sheet([
			["company", "default_income_account"],
			[PARENT, acct("Service", PARENT)],
			[CHILD_A, acct("Service", CHILD_A)],
		])
		out = import_sheet("company", url)
		flags = {c["company"]: c["company_is_group"] for c in out["changes"]}
		self.assertEqual(flags, {PARENT: 1, CHILD_A: 0})

	def test_export_selected_fields(self):
		frappe.local.response = frappe._dict()
		export_sheet("company", parent_company=PARENT, fields='["default_income_account"]')
		self.assertEqual(self._read_export_rows()[0], ["company", "default_income_account"])

		frappe.local.response = frappe._dict()
		export_sheet("item", item_group=ITEM_GROUP, parent_company=PARENT, fields="income_account")
		self.assertEqual(self._read_export_rows()[0], ["name", "item_name", "company", "income_account"])

		with self.assertRaises(frappe.ValidationError):
			export_sheet("company", parent_company=PARENT, fields='["abbr"]')

	def test_get_rows_unbounded_page_length(self):
		from account_bulk_config.api.company_accounts import get_rows as get_company_rows
		from account_bulk_config.api.item_defaults import get_rows as get_item_rows

		out_c = get_company_rows(parent_company=PARENT, page_length=0)
		self.assertEqual(len(out_c["rows"]), out_c["total"])
		self.assertEqual(out_c["total"], 3)

		out_i = get_item_rows("item", item_group=ITEM_GROUP, parent_company=PARENT, page_length=0)
		self.assertEqual(len(out_i["rows"]), out_i["total"])
		self.assertEqual(out_i["total"], 6)
