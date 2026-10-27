"""Tests for copying a parent company's chart of accounts to its children."""

import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.coa_sync import apply, preview
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_A_ABBR,
	CHILD_B,
	CHILD_B_ABBR,
	PARENT,
	PARENT_ABBR,
	setup_world,
)


def _own(rows, tag):
	# setup_world commits, so accounts of earlier tests stay in the plan
	return [r for r in rows if tag in r]


def _parent_of(company, account_name):
	return frappe.db.get_value(
		"Account", {"company": company, "account_name": account_name}, "parent_account"
	)


class TestCoaSync(IntegrationTestCase):
	def setUp(self):
		setup_world()
		self.tag = frappe.generate_hash(length=6)
		self.cash = frappe.db.get_value(
			"Account", {"company": PARENT, "account_name": "Cash In Hand", "is_group": 1}, "name"
		)

	def _parent_account(self, name, parent, is_group=0, sync=False, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"{name} {self.tag}",
				"company": PARENT,
				"parent_account": parent,
				"is_group": is_group,
				**values,
			}
		)
		# without sync: an account the children never got, as after a timed-out save
		doc.flags.ignore_root_company_validation = not sync
		doc.insert()
		return doc

	def test_missing_accounts_are_created_parents_first(self):
		group = self._parent_account("BAC Sync Grup", self.cash, is_group=1)
		ledger = self._parent_account("BAC Sync Kas", group.name, account_type="Cash")

		plans = {p["company"]: p for p in preview(PARENT)}
		self.assertEqual(
			_own([r["source"] for r in plans[CHILD_A]["create"]], self.tag), [group.name, ledger.name]
		)

		[result] = apply(PARENT, [CHILD_A])["results"]
		self.assertEqual((result["company"], result["error"]), (CHILD_A, None))
		self.assertEqual(_parent_of(CHILD_A, group.account_name), f"Cash In Hand - {CHILD_A_ABBR}")
		self.assertEqual(_parent_of(CHILD_A, ledger.account_name), f"{group.account_name} - {CHILD_A_ABBR}")
		self.assertEqual(
			frappe.db.get_value("Account", f"{ledger.account_name} - {CHILD_A_ABBR}", "account_type"), "Cash"
		)
		# only the picked child
		self.assertFalse(
			frappe.db.exists("Account", {"company": CHILD_B, "account_name": group.account_name})
		)

		[again] = preview(PARENT, [CHILD_A])
		self.assertEqual((again["create"], again["update"]), ([], []))
		self.assertEqual(again["issues"], [])

	def test_existing_accounts_get_the_parent_fields(self):
		ledger = self._parent_account("BAC Sync Bank", self.cash, account_type="Cash")
		apply(PARENT, [CHILD_B])
		child = f"{ledger.account_name} - {CHILD_B_ABBR}"
		frappe.db.set_value("Account", child, "account_type", "")

		[plan] = preview(PARENT, [CHILD_B])
		self.assertEqual(
			[u for u in plan["update"] if u["account"] == child],
			[{"account": child, "label": ledger.account_name, "values": {"account_type": "Cash"}}],
		)
		self.assertNotIn(
			child, [u["account"] for u in preview(PARENT, [CHILD_B], update_existing=0)[0]["update"]]
		)

		apply(PARENT, [CHILD_B])
		self.assertEqual(frappe.db.get_value("Account", child, "account_type"), "Cash")

	def test_group_mismatch_is_reported_not_created(self):
		group = self._parent_account("BAC Sync Beda", self.cash, is_group=1)
		ledger = self._parent_account("BAC Sync Isi", group.name)
		# the child has the group's name as a ledger
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": group.account_name,
				"company": CHILD_B,
				"parent_account": f"Cash In Hand - {CHILD_B_ABBR}",
			}
		)
		doc.flags.ignore_root_company_validation = True
		doc.insert()

		plans = {p["company"]: p for p in preview(PARENT)}
		self.assertEqual(_own([r["label"] for r in plans[CHILD_B]["create"]], self.tag), [])
		self.assertEqual(len(_own(plans[CHILD_B]["issues"], self.tag)), 1)
		self.assertEqual(len(_own([r["label"] for r in plans[CHILD_A]["create"]], self.tag)), 2)

		results = {r["company"]: r for r in apply(PARENT)["results"]}
		self.assertIsNone(results[CHILD_A]["error"])
		self.assertTrue(
			frappe.db.exists("Account", {"company": CHILD_A, "account_name": ledger.account_name})
		)
		self.assertFalse(
			frappe.db.exists("Account", {"company": CHILD_B, "account_name": ledger.account_name})
		)

	def test_saving_in_parent_copies_to_children_with_missing_ancestors(self):
		group = self._parent_account("BAC Sync Induk", self.cash, is_group=1)
		# ERPNext alone would refuse this save: the children lack the group
		ledger = self._parent_account("BAC Sync Baru", group.name, sync=True, account_type="Cash")
		self.assertTrue(ledger.flags.bac_sync_children)

		for company, abbr in ((CHILD_A, CHILD_A_ABBR), (CHILD_B, CHILD_B_ABBR)):
			self.assertEqual(_parent_of(company, ledger.account_name), f"{group.account_name} - {abbr}")
		self.assertEqual(ledger.name, f"{ledger.account_name} - {PARENT_ABBR}")

		ledger.account_type = "Bank"
		ledger.save()
		self.assertEqual(
			frappe.db.get_value("Account", f"{ledger.account_name} - {CHILD_A_ABBR}", "account_type"), "Bank"
		)

	def test_only_the_top_company_is_a_source(self):
		with self.assertRaises(frappe.ValidationError):
			preview(CHILD_A)
