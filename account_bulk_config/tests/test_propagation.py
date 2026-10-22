import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.propagation import descendants, map_value, preview_propagation
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	ITEM_1,
	PARENT,
	acct,
	setup_world,
)


def set_company(company: str, field: str, value: str | None) -> None:
	frappe.db.set_value("Company", company, field, value)


class TestPropagation(IntegrationTestCase):
	def setUp(self):
		setup_world()

	def test_map_value_prefix_abbr(self):
		src = acct("Debtors", PARENT)  # "... - BACP"
		self.assertEqual(map_value("Account", src, PARENT, CHILD_A), (acct("Debtors", CHILD_A), True))
		self.assertEqual(map_value("Account", src, PARENT, CHILD_B), (acct("Debtors", CHILD_B), True))

	def test_map_value_edge_cases(self):
		self.assertEqual(map_value("Account", None, PARENT, CHILD_A), (None, True))
		self.assertEqual(
			map_value("Price List", "Standard Selling", PARENT, CHILD_A), ("Standard Selling", True)
		)
		self.assertEqual(map_value("Account", "Ghost - BACP", PARENT, CHILD_A), ("Ghost - BACPA", False))
		self.assertEqual(map_value("Account", acct("Debtors", CHILD_B), PARENT, CHILD_A)[1], False)

	def test_descendants(self):
		self.assertEqual(set(descendants(PARENT, "children")), {CHILD_A, CHILD_B})
		self.assertEqual(descendants(CHILD_A, "all"), [])

	def test_preview_statuses(self):
		f = "default_income_account"
		set_company(CHILD_A, f, acct("Sales", CHILD_A))  # follows parent
		set_company(CHILD_B, f, acct("Service", CHILD_B))  # exception
		set_company(PARENT, f, acct("Sales", PARENT))
		chg = {
			"name": PARENT,
			"company": PARENT,
			"field": f,
			"old": acct("Sales", PARENT),
			"new": acct("Service", PARENT),
		}
		rows = {r["company"]: r for r in preview_propagation("company", [chg])}
		self.assertEqual((rows[CHILD_A]["status"], rows[CHILD_A]["checked"]), ("changed", True))
		self.assertEqual(rows[CHILD_A]["new"], acct("Service", CHILD_A))
		self.assertEqual((rows[CHILD_B]["status"], rows[CHILD_B]["checked"]), ("same", False))

	def test_preview_exception_and_not_found(self):
		f = "default_income_account"
		set_company(PARENT, f, acct("Sales", PARENT))
		set_company(CHILD_A, f, acct("Sales", CHILD_A))
		set_company(CHILD_B, f, acct("Round Off", CHILD_B))  # third value -> exception
		chg = {
			"name": PARENT,
			"company": PARENT,
			"field": f,
			"old": acct("Sales", PARENT),
			"new": acct("Service", PARENT),
		}
		rows = {r["company"]: r for r in preview_propagation("company", [chg])}
		self.assertEqual((rows[CHILD_B]["status"], rows[CHILD_B]["checked"]), ("exception", False))

		# new = "Ghost - BACP" -> "not_found"
		chg_ghost = {
			"name": PARENT,
			"company": PARENT,
			"field": f,
			"old": acct("Sales", PARENT),
			"new": "Ghost - BACP",
		}
		rows_ghost = {r["company"]: r for r in preview_propagation("company", [chg_ghost])}
		self.assertEqual(
			(rows_ghost[CHILD_A]["status"], rows_ghost[CHILD_A]["checked"]), ("not_found", False)
		)

	def test_preview_blank_parent_clears_child(self):
		f = "default_income_account"
		set_company(CHILD_A, f, acct("Sales", CHILD_A))
		set_company(PARENT, f, acct("Sales", PARENT))
		chg = {"name": PARENT, "company": PARENT, "field": f, "old": acct("Sales", PARENT), "new": None}
		rows = {r["company"]: r for r in preview_propagation("company", [chg])}
		self.assertEqual((rows[CHILD_A]["status"], rows[CHILD_A]["checked"]), ("changed", True))
		self.assertIsNone(rows[CHILD_A]["new"])
		# RPC sends a null `targets` as an empty string (depth switch in the dialog)
		self.assertEqual(preview_propagation("company", [chg], targets=""), list(rows.values()))
		self.assertEqual(rows[CHILD_A]["old"], acct("Sales", CHILD_A))

	def test_preview_item_child_without_row(self):
		frappe.db.delete("Item Default", {"parent": ITEM_1})
		chg = {
			"name": ITEM_1,
			"company": PARENT,
			"field": "income_account",
			"old": None,
			"new": acct("Sales", PARENT),
		}
		rows = {r["company"]: r for r in preview_propagation("item", [chg])}
		self.assertEqual((rows[CHILD_A]["status"], rows[CHILD_A]["checked"]), ("changed", True))
		self.assertIsNone(rows[CHILD_A]["old"])
		self.assertEqual(rows[CHILD_A]["new"], acct("Sales", CHILD_A))

	def test_preview_explicit_targets(self):
		f = "default_income_account"
		set_company(CHILD_A, f, acct("Sales", CHILD_A))
		chg = {
			"name": CHILD_A,
			"company": CHILD_A,
			"field": f,
			"old": acct("Sales", CHILD_A),
			"new": acct("Service", CHILD_A),
		}
		rows = preview_propagation("company", [chg], targets=[CHILD_A, CHILD_B])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["company"], CHILD_B)
		self.assertEqual(rows[0]["name"], CHILD_B)
		self.assertEqual(rows[0]["new"], acct("Service", CHILD_B))
