import json
import os

import frappe
from frappe.modules.import_file import get_file_path
from frappe.tests import IntegrationTestCase


class TestPagesAndWorkspace(IntegrationTestCase):
	def test_page_files_and_render_include(self):
		for page_name in ("bulk_company_accounts", "bulk_item_defaults"):
			path = get_file_path("Bulk Account Config", "Page", page_name)
			self.assertTrue(os.path.exists(path), f"JSON file missing: {path}")

			doc = frappe.new_doc("Page")
			doc.name = page_name.replace("_", "-")
			doc.module = "Bulk Account Config"
			doc.load_assets()

			self.assertIn("BulkGrid", doc.script, f"BulkGrid include failed for {page_name}")
			self.assertTrue(len(doc.style or "") > 0, f"CSS missing for {page_name}")

	def test_workspace_file_definition(self):
		path = get_file_path("Bulk Account Config", "Workspace", "bulk_account_config")
		self.assertTrue(os.path.exists(path), f"Workspace JSON missing: {path}")

		with open(path, encoding="utf-8") as f:
			data = json.load(f)

		self.assertEqual(data.get("public"), 1)
		self.assertEqual(data.get("module"), "Bulk Account Config")
		shortcuts = {s["link_to"]: s["type"] for s in data.get("shortcuts", [])}
		self.assertEqual(shortcuts.get("bulk-company-accounts"), "Page")
		self.assertEqual(shortcuts.get("bulk-item-defaults"), "Page")

	def test_app_screen_and_sidebar(self):
		from account_bulk_config.api.permission import has_app_permission

		entry = frappe.get_hooks("add_to_apps_screen", app_name="account_bulk_config")[0]
		self.assertEqual(entry["route"], "/desk/bulk-account-config")
		self.assertTrue(os.path.exists(frappe.get_app_path("account_bulk_config", "public", "images", "logo.svg")))
		self.assertTrue(has_app_permission())  # tests run as Administrator

		sidebar = frappe.get_doc("Sidebar", "Bulk Account Config")
		self.assertEqual(sidebar.app, "account_bulk_config")
		self.assertEqual(
			[i.link_to for i in sidebar.items if i.type == "Link"][:3],
			["Bulk Account Config", "bulk-company-accounts", "bulk-item-defaults"],
		)
