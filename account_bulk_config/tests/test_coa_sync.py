"""Tests for copying a parent company's chart of accounts to its children."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.coa_sync import (
	CHAIN_PARENT,
	EVENT,
	MAX_ATTEMPTS,
	apply,
	preview,
	resume_stalled,
	run_job,
	update_account_number,
)
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
		# These tests exercise inline results even when shared fixtures need a large sync.
		inline = patch("account_bulk_config.api.coa_sync.SYNC_LIMIT", float("inf"))
		inline.start()
		self.addCleanup(inline.stop)
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
		self.assertEqual(again["create"], [])
		self.assertEqual([u for u in again["update"] if self.tag in u["account"]], [])
		self.assertEqual(_own(again["issues"], self.tag), [])

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

	def test_account_category_is_copied_and_synced(self):
		category = frappe.get_doc(
			{
				"doctype": "Account Category",
				"account_category_name": f"BAC Sync Category {self.tag}",
				"root_type": "Asset",
			}
		).insert()
		ledger = self._parent_account("BAC Sync Category", self.cash, account_category=category.name)
		[result] = apply(PARENT, [CHILD_B])["results"]
		self.assertIsNone(result["error"])
		child = f"{ledger.account_name} - {CHILD_B_ABBR}"
		self.assertEqual(frappe.db.get_value("Account", child, "account_category"), category.name)

		frappe.db.set_value("Account", child, "account_category", None)
		[plan] = preview(PARENT, [CHILD_B])
		self.assertEqual(
			[u["values"] for u in plan["update"] if u["account"] == child],
			[{"account_category": category.name}],
		)
		[disabled] = preview(PARENT, [CHILD_B], update_existing=0)
		self.assertNotIn(child, [u["account"] for u in disabled["update"]])
		apply(PARENT, [CHILD_B], update_existing=0)
		self.assertFalse(frappe.db.get_value("Account", child, "account_category"))

		[result] = apply(PARENT, [CHILD_B])["results"]
		self.assertIsNone(result["error"])
		self.assertEqual(frappe.db.get_value("Account", child, "account_category"), category.name)

		frappe.db.set_value("Account", ledger.name, "account_category", None)
		[result] = apply(PARENT, [CHILD_B])["results"]
		self.assertIsNone(result["error"])
		self.assertFalse(frappe.db.get_value("Account", child, "account_category"))
		[again] = preview(PARENT, [CHILD_B])
		self.assertNotIn(child, [u["account"] for u in again["update"]])

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

		# Inline jobs changed nested-set positions after this instance was inserted.
		ledger.reload()
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

	def test_same_number_follows_the_parent_name(self):
		number = frappe.generate_hash(length=8)
		source = self._parent_account("BAC Sync Nomor", self.cash, account_number=number)
		old_name = f"BAC Sync Milik Anak {self.tag}"
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": old_name,
				"account_number": number,
				"company": CHILD_A,
				"parent_account": f"Cash In Hand - {CHILD_A_ABBR}",
			}
		)
		doc.flags.ignore_root_company_validation = True
		doc.insert()
		child = doc.name

		[plan] = preview(PARENT, [CHILD_A])
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(_own(plan["issues"], self.tag), [])
		[row] = [u for u in plan["update"] if u["account"] == child]
		self.assertEqual(row["account_name"], source.account_name)

		apply(PARENT, [CHILD_A])
		expected = f"{number} - {source.account_name} - {CHILD_A_ABBR}"
		self.assertEqual(
			frappe.db.get_value("Account", {"company": CHILD_A, "account_number": number}, "name"), expected
		)
		self.assertEqual(frappe.db.count("Account", {"company": CHILD_A, "account_number": number}), 1)

	def test_duplicate_names_and_renamed_copies_follow_their_number(self):
		group_a = self._parent_account("BAC Sync Grup A", self.cash, is_group=1)
		group_b = self._parent_account("BAC Sync Grup B", self.cash, is_group=1)
		apply(PARENT, [CHILD_A])
		group_a_child = f"{group_a.account_name} - {CHILD_A_ABBR}"
		group_b_child = f"{group_b.account_name} - {CHILD_A_ABBR}"
		number_a, number_b = f"1{self.tag}", f"2{self.tag}"
		source_a = self._parent_account("BAC Sync Kembar", group_a.name, account_number=number_a)
		source_b = self._parent_account("BAC Sync Kembar", group_b.name, account_number=number_b)
		for number, name, parent in (
			(number_a, f"BAC Sync Lama A {self.tag}", group_a_child),
			(number_b, f"BAC Sync Lama B {self.tag}", group_b_child),
		):
			doc = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": name,
					"account_number": number,
					"company": CHILD_A,
					"parent_account": parent,
				}
			)
			doc.flags.ignore_root_company_validation = True
			doc.insert()

		[plan] = preview(PARENT, [CHILD_A])
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(_own(plan["issues"], self.tag), [])

		apply(PARENT, [CHILD_A])
		for source, parent in ((source_a, group_a_child), (source_b, group_b_child)):
			child = frappe.db.get_value(
				"Account", {"company": CHILD_A, "account_number": source.account_number}, "name"
			)
			self.assertEqual(child, f"{source.account_number} - {source.account_name} - {CHILD_A_ABBR}")
			self.assertEqual(frappe.db.get_value("Account", child, "parent_account"), parent)

	def test_ambiguous_name_is_reported_not_created(self):
		parent = f"Cash In Hand - {CHILD_A_ABBR}"
		children = []
		for number in (f"1{self.tag}", f"2{self.tag}"):
			doc = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"BAC Sync Ambigu {self.tag}",
					"account_number": number,
					"company": CHILD_A,
					"parent_account": parent,
				}
			)
			doc.flags.ignore_root_company_validation = True
			doc.insert()
			children.append(doc.name)
		source = self._parent_account("BAC Sync Ambigu", self.cash)
		self.addCleanup(frappe.delete_doc, "Account", source.name)
		for name in children:
			self.addCleanup(frappe.delete_doc, "Account", name)

		[plan] = preview(PARENT, [CHILD_A], delete_missing=1)
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(len(_own(plan["issues"], self.tag)), 1)
		deleted = [r["account"] for r in plan["delete"]]
		for name in children:
			self.assertNotIn(name, deleted)

	def test_ambiguous_group_branch_is_not_deleted(self):
		parent = f"Cash In Hand - {CHILD_A_ABBR}"
		names = []
		for number in (f"3{self.tag}", f"4{self.tag}"):
			group = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"BAC Sync Ambigu Grup {self.tag}",
					"account_number": number,
					"company": CHILD_A,
					"parent_account": parent,
					"is_group": 1,
				}
			)
			group.flags.ignore_root_company_validation = True
			group.insert()
			child = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"BAC Sync Ambigu Isi {number}",
					"company": CHILD_A,
					"parent_account": group.name,
				}
			)
			child.flags.ignore_root_company_validation = True
			child.insert()
			names += [group.name, child.name]
		source = self._parent_account("BAC Sync Ambigu Grup", self.cash, is_group=1)
		self.addCleanup(frappe.delete_doc, "Account", source.name)
		for name in names:
			self.addCleanup(frappe.delete_doc, "Account", name)

		[plan] = preview(PARENT, [CHILD_A], delete_missing=1)
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(len(_own(plan["issues"], self.tag)), 1)
		deleted = [r["account"] for r in plan["delete"]]
		for name in names:
			self.assertNotIn(name, deleted)

	def test_single_account_job_uses_the_full_source_to_match(self):
		group = self._parent_account("BAC Sync Cabang", self.cash, is_group=1)
		apply(PARENT, [CHILD_A])
		group_child = f"{group.account_name} - {CHILD_A_ABBR}"
		source_a = self._parent_account("BAC Sync Penjualan", group.name, account_number=f"5{self.tag}")
		source_b = self._parent_account("BAC Sync Penjualan", group.name, account_number=f"6{self.tag}")
		self.addCleanup(frappe.delete_doc, "Account", source_a.name)
		self.addCleanup(frappe.delete_doc, "Account", source_b.name)
		copy = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"BAC Sync Penjualan {self.tag}",
				"account_number": f"7{self.tag}",
				"company": CHILD_A,
				"parent_account": group_child,
			}
		)
		copy.flags.ignore_root_company_validation = True
		copy.insert()
		self.addCleanup(frappe.delete_doc, "Account", copy.name)

		with patch("account_bulk_config.api.coa_sync.frappe.publish_realtime") as publish:
			run_job(PARENT, [CHILD_A], accounts=[source_a.name])

		copy.reload()
		self.assertEqual(copy.parent_account, group_child)
		self.assertEqual(copy.account_number, f"7{self.tag}")
		results = [c.args[1] for c in publish.call_args_list if c.args[0] == EVENT]
		self.assertTrue(
			any("BAC Sync Penjualan" in i for b in results for r in b["results"] for i in r["issues"])
		)

	def test_case_only_rename_replaces_the_copy(self):
		ledger = self._parent_account("BAC Sync Case", self.cash)
		apply(PARENT, [CHILD_A])
		child = f"{ledger.account_name} - {CHILD_A_ABBR}"
		lower = ledger.account_name.lower()
		frappe.db.set_value("Account", ledger.name, "account_name", lower)

		def drop(name):
			if frappe.db.exists("Account", name):
				frappe.delete_doc("Account", name, force=True)

		self.addCleanup(drop, ledger.name)
		self.addCleanup(drop, child)

		[plan] = preview(PARENT, [CHILD_A])
		[row] = [u for u in plan["update"] if u["account"] == child]
		self.assertEqual(row["account_name"], lower)

		out = apply(PARENT, [CHILD_A])
		self.assertIn("job_id", out)
		name = frappe.db.get_value("Account", {"company": CHILD_A, "account_name": lower}, "name")
		self.assertEqual(name, f"{lower} - {CHILD_A_ABBR}")

	def test_case_only_doc_rename_matches_the_old_copy(self):
		ledger = self._parent_account("BAC Sync Doc Case", self.cash)
		apply(PARENT, [CHILD_A])
		child = f"{ledger.account_name} - {CHILD_A_ABBR}"
		lower = ledger.account_name.lower()
		new_doc = f"{lower} - {PARENT_ABBR}"
		frappe.rename_doc("Account", ledger.name, new_doc, force=True, show_alert=False)
		frappe.db.set_value("Account", new_doc, "account_name", lower)

		def drop(name):
			if frappe.db.exists("Account", name):
				frappe.delete_doc("Account", name, force=True)

		self.addCleanup(drop, new_doc)
		self.addCleanup(drop, child)

		[plan] = preview(PARENT, [CHILD_A], delete_missing=1)
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertNotIn(child, [r["account"] for r in plan["delete"]])
		[row] = [u for u in plan["update"] if u["account"] == child]
		self.assertEqual(row["account_name"], lower)

		apply(PARENT, [CHILD_A])
		name = frappe.db.get_value("Account", {"company": CHILD_A, "account_name": lower}, "name")
		self.assertEqual(name, f"{lower} - {CHILD_A_ABBR}")

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

	def test_used_accounts_stay_with_their_group(self):
		group = self._parent_account("BAC Sync Grup Hapus", self.cash, is_group=1)
		used = self._parent_account("BAC Sync Dipakai", group.name)
		unused = self._parent_account("BAC Sync Tak Dipakai", group.name)
		apply(PARENT, [CHILD_A])
		group_child = f"{group.account_name} - {CHILD_A_ABBR}"
		used_child = f"{used.account_name} - {CHILD_A_ABBR}"
		unused_child = f"{unused.account_name} - {CHILD_A_ABBR}"
		frappe.delete_doc("Account", used.name)
		frappe.delete_doc("Account", unused.name)

		with patch("account_bulk_config.api.coa_sync._used_accounts", return_value={used_child}):
			[plan] = preview(PARENT, [CHILD_A], delete_missing=1)
		self.assertIn(unused_child, [r["account"] for r in plan["delete"]])
		self.assertNotIn(used_child, [r["account"] for r in plan["delete"]])
		self.assertEqual([r["account"] for r in plan["kept"]], [used_child])

		with patch("account_bulk_config.api.coa_sync._used_accounts", return_value={used_child}):
			[result] = apply(PARENT, [CHILD_A], delete_missing=1)["results"]
		self.assertEqual(result["kept"], [used_child])
		self.assertGreaterEqual(result["deleted"], 1)
		self.assertTrue(frappe.db.exists("Account", group_child))
		self.assertTrue(frappe.db.exists("Account", used_child))
		self.assertFalse(frappe.db.exists("Account", unused_child))

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

	def test_background_copy_runs_in_batches_that_each_report(self):
		ledger = self._parent_account("BAC Sync Batch", self.cash)
		with (
			patch("account_bulk_config.api.coa_sync.CHUNK", 1),
			patch("account_bulk_config.api.coa_sync.frappe.publish_realtime") as publish,
		):
			run_job(PARENT, [CHILD_A, CHILD_B], bac_job_id="bac_test")

		for abbr in (CHILD_A_ABBR, CHILD_B_ABBR):
			self.assertTrue(frappe.db.exists("Account", f"{ledger.account_name} - {abbr}"))
		batches = [c.args[1] for c in publish.call_args_list if c.args[0] == EVENT]
		self.assertEqual(
			[(b["job_id"], b["done"], b["total"]) for b in batches], [("bac_test", 1, 2), ("bac_test", 2, 2)]
		)
		self.assertEqual([r["company"] for b in batches for r in b["results"]], [CHILD_A, CHILD_B])

	def _stalled_chain(self, companies, attempts=0):
		# what a batch leaves behind when its worker dies mid-copy
		state = {
			"method": "run_job",
			"queue": "long",
			"companies": companies,
			"done": 0,
			"total": len(companies),
			"attempts": attempts,
			"at": "2000-01-01 00:00:00",
			"kwargs": {
				"parent_company": PARENT,
				"update_existing": 1,
				"delete_missing": 0,
				"user": "Administrator",
			},
		}
		frappe.defaults.set_default("bac_coa_test", json.dumps(state), CHAIN_PARENT)

	def test_stalled_chain_is_resumed(self):
		ledger = self._parent_account("BAC Sync Lanjut", self.cash)
		self._stalled_chain([CHILD_A])

		resume_stalled()
		self.assertTrue(frappe.db.exists("Account", f"{ledger.account_name} - {CHILD_A_ABBR}"))
		self.assertFalse(frappe.db.exists("DefaultValue", {"parent": CHAIN_PARENT, "defkey": "bac_coa_test"}))

	def test_batch_that_keeps_dying_is_skipped_and_reported(self):
		ledger = self._parent_account("BAC Sync Mati", self.cash)
		self._stalled_chain([CHILD_B, CHILD_A], attempts=MAX_ATTEMPTS - 1)
		with (
			patch("account_bulk_config.api.coa_sync.CHUNK", 1),
			patch("account_bulk_config.api.coa_sync.frappe.publish_realtime") as publish,
		):
			resume_stalled()

		batches = [c.args[1] for c in publish.call_args_list if c.args[0] == EVENT]
		self.assertIn(CHILD_B, batches[0]["error"])
		self.assertEqual([(b["done"], b["total"]) for b in batches], [(1, 2), (2, 2)])
		self.assertFalse(frappe.db.exists("Account", f"{ledger.account_name} - {CHILD_B_ABBR}"))
		self.assertTrue(frappe.db.exists("Account", f"{ledger.account_name} - {CHILD_A_ABBR}"))

	def test_copy_to_any_company_not_only_children(self):
		cash_a = f"Cash In Hand - {CHILD_A_ABBR}"
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"BAC Sync Saudara {self.tag}",
				"company": CHILD_A,
				"parent_account": cash_a,
			}
		)
		doc.flags.ignore_root_company_validation = True
		doc.insert()

		# CHILD_B is CHILD_A's sibling, not its child
		self.assertEqual(preview(CHILD_A, [CHILD_B]), [])
		# the source itself is never a target
		self.assertEqual(
			[p["company"] for p in preview(CHILD_A, [CHILD_B, CHILD_A], any_company=1)], [CHILD_B]
		)
		run_job(CHILD_A, [CHILD_B], any_company=1)
		self.assertEqual(_parent_of(CHILD_B, doc.account_name), f"Cash In Hand - {CHILD_B_ABBR}")

	def test_copy_to_any_company_in_background_batches(self):
		ledger = self._parent_account("BAC Sync Bebas", self.cash)
		with patch("account_bulk_config.api.coa_sync.SYNC_LIMIT", 0):
			out = apply(PARENT, [CHILD_B], any_company=1)
		self.assertEqual(out["companies"], 1)
		self.assertTrue(frappe.db.exists("Account", f"{ledger.account_name} - {CHILD_B_ABBR}"))

	def test_a_root_the_target_lacks_is_reported_not_created(self):
		root = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"BAC Sync Akar {self.tag}",
				"company": CHILD_A,
				"is_group": 1,
				"root_type": "Asset",
				"report_type": "Balance Sheet",
			}
		)
		root.flags.ignore_root_company_validation = True
		# ERPNext inserts its own roots the same way: they have no parent account
		root.flags.ignore_mandatory = True
		root.insert()
		child = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"BAC Sync Di Akar {self.tag}",
				"company": CHILD_A,
				"parent_account": root.name,
			}
		)
		child.flags.ignore_root_company_validation = True
		child.insert()

		[plan] = preview(CHILD_A, [CHILD_B], any_company=1)
		self.assertEqual(_own([r["label"] for r in plan["create"]], self.tag), [])
		self.assertEqual(len(_own(plan["issues"], self.tag)), 1)
