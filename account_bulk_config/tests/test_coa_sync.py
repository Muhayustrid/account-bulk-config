"""Tests for copying a parent company's chart of accounts to its children."""

import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.coa_sync import apply, preview, run_job, update_account_number
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

	def test_blank_freeze_account_equals_no(self):
		ledger = self._parent_account("BAC Sync Freeze", self.cash, freeze_account="No")
		apply(PARENT, [CHILD_B])
		child = f"{ledger.account_name} - {CHILD_B_ABBR}"
		frappe.db.set_value("Account", child, "freeze_account", None)

		[plan] = preview(PARENT, [CHILD_B])
		self.assertNotIn(child, [u["account"] for u in plan["update"]])

	def test_existing_accounts_get_the_parent_fields(self):
		ledger = self._parent_account("BAC Sync Bank", self.cash, account_type="Cash")
		apply(PARENT, [CHILD_B])
		child = f"{ledger.account_name} - {CHILD_B_ABBR}"
		frappe.db.set_value("Account", child, "account_type", "")

		[plan] = preview(PARENT, [CHILD_B])
		self.assertEqual(
			[u["values"] for u in plan["update"] if u["account"] == child], [{"account_type": "Cash"}]
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

	def test_a_company_that_has_a_parent_can_be_the_source(self):
		# CHILD_A has a parent but no children of its own
		self.assertEqual(preview(CHILD_A), [])

	def test_moved_account_follows_the_parent(self):
		old = self._parent_account("BAC Sync Lama", self.cash, is_group=1)
		new = self._parent_account("BAC Sync Pindah", self.cash, is_group=1)
		ledger = self._parent_account("BAC Sync Geser", old.name)
		apply(PARENT, [CHILD_A])

		ledger.parent_account = new.name
		ledger.flags.ignore_root_company_validation = True
		ledger.save()

		[plan] = preview(PARENT, [CHILD_A])
		child = f"{ledger.account_name} - {CHILD_A_ABBR}"
		self.assertIn(child, [u["account"] for u in plan["update"]])
		apply(PARENT, [CHILD_A])
		self.assertEqual(_parent_of(CHILD_A, ledger.account_name), f"{new.account_name} - {CHILD_A_ABBR}")

	def test_a_refused_account_does_not_block_the_others(self):
		frozen = self._parent_account("BAC Sync Beku", self.cash, freeze_account="Yes")
		apply(PARENT, [CHILD_B])
		child = f"{frozen.account_name} - {CHILD_B_ABBR}"
		frappe.db.set_value("Account", child, "freeze_account", "No")
		frappe.db.set_value("Company", CHILD_B, "role_allowed_for_frozen_entries", None)
		ledger = self._parent_account("BAC Sync Lolos", self.cash)

		[result] = apply(PARENT, [CHILD_B])["results"]
		# ERPNext refuses the freeze without the frozen-entries role; the new account still goes in
		self.assertEqual(len(_own(result["issues"], self.tag)), 1)
		self.assertTrue(frappe.db.exists("Account", f"{ledger.account_name} - {CHILD_B_ABBR}"))

	def test_used_account_number_is_reported_not_created(self):
		number = frappe.generate_hash(length=8)
		self._parent_account("BAC Sync Nomor", self.cash, account_number=number)
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"BAC Sync Milik Anak {self.tag}",
				"account_number": number,
				"company": CHILD_A,
				"parent_account": f"Cash In Hand - {CHILD_A_ABBR}",
			}
		)
		doc.flags.ignore_root_company_validation = True
		doc.insert()

		[plan] = preview(PARENT, [CHILD_A])
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(len(_own(plan["issues"], self.tag)), 1)

	def test_renumbered_parent_account_renumbers_the_copy(self):
		ledger = self._parent_account("BAC Sync Renomor", self.cash)
		apply(PARENT, [CHILD_A])
		number = frappe.generate_hash(length=8)
		frappe.db.set_value("Account", ledger.name, "account_number", number)

		[plan] = preview(PARENT, [CHILD_A])
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		[row] = [u for u in plan["update"] if self.tag in u["account"]]
		self.assertEqual(row["account_number"], number)

		run_job(PARENT, [CHILD_A])
		self.assertTrue(frappe.db.exists("Account", f"{number} - {ledger.account_name} - {CHILD_A_ABBR}"))

	def test_accounts_gone_from_the_parent_are_deleted_only_on_request(self):
		ledger = self._parent_account("BAC Sync Hapus", self.cash)
		apply(PARENT, [CHILD_A])
		child = f"{ledger.account_name} - {CHILD_A_ABBR}"
		frappe.delete_doc("Account", ledger.name)

		[plan] = preview(PARENT, [CHILD_A])
		self.assertEqual(plan["delete"], [])
		[plan] = preview(PARENT, [CHILD_A], delete_missing=1)
		self.assertIn(child, [r["account"] for r in plan["delete"]])

		apply(PARENT, [CHILD_A], delete_missing=1)
		self.assertFalse(frappe.db.exists("Account", child))

	def test_renaming_in_parent_renames_the_copies(self):
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")[
				"erpnext.accounts.doctype.account.account.update_account_number"
			][-1],
			"account_bulk_config.api.coa_sync.update_account_number",
		)
		ledger = self._parent_account("BAC Sync Nama", self.cash)
		apply(PARENT, [CHILD_A, CHILD_B])
		name = f"BAC Sync Nama Baru {self.tag}"
		number = frappe.generate_hash(length=8)

		new = update_account_number(ledger.name, name, number)
		self.assertEqual(new, f"{number} - {name} - {PARENT_ABBR}")
		for abbr in (CHILD_A_ABBR, CHILD_B_ABBR):
			self.assertTrue(frappe.db.exists("Account", f"{number} - {name} - {abbr}"))
			self.assertFalse(frappe.db.exists("Account", f"{ledger.account_name} - {abbr}"))
