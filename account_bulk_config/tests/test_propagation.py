import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.propagation import descendants, map_value, preview_copy, preview_propagation
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	ITEM_1,
	ITEM_2,
	ITEM_GROUP,
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

	def test_preview_query_count_independent_of_rows(self):
		fields = ["income_account", "expense_account", "default_warehouse", "default_price_list"]
		chgs = [
			{"name": n, "company": PARENT, "field": f, "old": None, "new": acct("Sales", PARENT)}
			for n in (ITEM_1, ITEM_2)
			for f in fields
		]
		preview_propagation("item", chgs)  # warm doctype meta caches; only data queries are counted
		# is_group + descendants + abbrs + one existence check per link doctype + current values
		with self.assertQueryCount(8, query_type=("select",)):
			rows = preview_propagation("item", chgs * 10)
		self.assertEqual(len(rows), len(chgs) * 10 * 2)

	def test_preview_copy_without_filter_child_to_parent(self):
		frappe.db.delete("Item Default", {"parent": ["in", [ITEM_1, ITEM_2, ITEM_GROUP]]})
		for parent, parenttype in ((ITEM_1, "Item"), (ITEM_2, "Item")):
			doc = frappe.get_doc(parenttype, parent)
			doc.append("item_defaults", {"company": CHILD_A, "income_account": acct("Sales", CHILD_A)})
			doc.save()
		out = preview_copy("item", CHILD_A, ["income_account"], targets=[PARENT])
		self.assertEqual({c["name"] for c in out["changes"]}, {ITEM_1, ITEM_2})
		by_item = {r["name"]: r for r in out["rows"]}
		self.assertEqual(set(by_item), {ITEM_1, ITEM_2})
		self.assertEqual(by_item[ITEM_1]["company"], PARENT)
		self.assertEqual(by_item[ITEM_1]["new"], acct("Sales", PARENT))
		self.assertEqual(by_item[ITEM_1]["status"], "changed")

	def test_preview_copy_item_group_filter(self):
		frappe.db.delete("Item Default", {"parent": ["in", [ITEM_1, ITEM_2, ITEM_GROUP]]})
		doc = frappe.get_doc("Item", ITEM_1)
		doc.append("item_defaults", {"company": PARENT, "income_account": acct("Sales", PARENT)})
		doc.save()
		# the filter group's subtree holds ITEM_1; an unrelated group holds none of the test items
		out = preview_copy("item", PARENT, ["income_account"], item_group=ITEM_GROUP, depth="children")
		self.assertEqual({(r["name"], r["company"]) for r in out["rows"]}, {(ITEM_1, CHILD_A), (ITEM_1, CHILD_B)})
		empty = preview_copy("item", PARENT, ["income_account"], item_group="Ghost Group")
		self.assertEqual(empty, {"changes": [], "rows": []})
