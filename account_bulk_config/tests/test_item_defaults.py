import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.batch import apply_changes
from account_bulk_config.api.item_defaults import get_rows
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	ITEM_1,
	ITEM_2,
	ITEM_GROUP,
	PARENT,
	acct,
	make_user_with_roles,
	setup_world,
)


def current(parent: str, company: str, field: str = "income_account") -> str | None:
	return frappe.db.get_value("Item Default", {"parent": parent, "company": company}, field) or None


class TestItemDefaults(IntegrationTestCase):
	def setUp(self):
		setup_world()
		frappe.db.delete("Item Default", {"parent": ["in", [ITEM_1, ITEM_2, ITEM_GROUP]]})

	def test_new_row_created(self):
		res = apply_changes(
			"item",
			[
				{
					"name": ITEM_1,
					"company": CHILD_A,
					"field": "income_account",
					"old": None,
					"new": acct("Sales", CHILD_A),
				}
			],
		)
		self.assertEqual(res[0]["status"], "ok")
		rows = frappe.get_all("Item Default", {"parent": ITEM_1, "company": CHILD_A}, pluck="income_account")
		self.assertEqual(rows, [acct("Sales", CHILD_A)])

	def test_many_companies_one_save(self):
		before = frappe.db.count("Version", {"ref_doctype": "Item", "docname": ITEM_2})
		apply_changes(
			"item",
			[
				{
					"name": ITEM_2,
					"company": c,
					"field": "income_account",
					"old": current(ITEM_2, c),
					"new": acct("Sales", c),
				}
				for c in (CHILD_A, CHILD_B)
			],
		)
		self.assertEqual(frappe.db.count("Version", {"ref_doctype": "Item", "docname": ITEM_2}), before + 1)

	def test_item_group_no_duplicate_company(self):
		for _ in range(2):
			apply_changes(
				"item_group",
				[
					{
						"name": ITEM_GROUP,
						"company": CHILD_A,
						"field": "income_account",
						"old": current(ITEM_GROUP, CHILD_A),
						"new": acct("Sales", CHILD_A),
					}
				],
			)
		self.assertEqual(frappe.db.count("Item Default", {"parent": ITEM_GROUP, "company": CHILD_A}), 1)

	def test_get_rows_pairs_and_paging(self):
		out = get_rows("item", item_group=ITEM_GROUP, parent_company=PARENT, start=0, page_length=4)
		self.assertEqual(out["total"], 2 * 3)
		self.assertEqual(len(out["rows"]), 4)
		self.assertEqual(out["rows"][0]["name"], ITEM_1)
		self.assertEqual(out["rows"][0]["label"], frappe.db.get_value("Item", ITEM_1, "item_name"))
		group_rows = get_rows("item_group", item_group=ITEM_GROUP, parent_company=PARENT)["rows"]
		self.assertEqual(group_rows[0]["label"], group_rows[0]["name"])

	def test_no_write_permission(self):
		user = make_user_with_roles("bac-acct@example.com", ["Accounts Manager"])
		with self.set_user(user):
			res = apply_changes(
				"item",
				[
					{
						"name": ITEM_1,
						"company": CHILD_A,
						"field": "income_account",
						"old": current(ITEM_1, CHILD_A),
						"new": acct("Sales", CHILD_A),
					}
				],
			)
		self.assertEqual(res[0]["status"], "error")
