"""Tests for correcting the account of one submitted document."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from account_bulk_config.api.voucher_fix import apply, get_values, preview
from account_bulk_config.tests import test_ledger_update
from account_bulk_config.tests.test_ledger_update import (
	ABBR,
	CHILD_A,
	DEBTORS,
	DEBTORS_2,
	DP,
	KAS_KECIL,
	MAIN_CC,
	SALES,
	_live_gl_accounts,
)


class TestVoucherFix(IntegrationTestCase):
	# same world and document factories as the bulk ledger update
	# imported via the module so the runner does not collect TestLedgerUpdate here too
	setUp = test_ledger_update.TestLedgerUpdate.setUp
	_journal = test_ledger_update.TestLedgerUpdate._journal
	_invoice = test_ledger_update.TestLedgerUpdate._invoice

	def test_journal_account_is_corrected(self):
		je = self._journal(DP)

		values = {v["value"] for v in get_values("Journal Entry", je.name)["values"]}
		self.assertEqual(values, {DP, SALES})

		result = apply("Journal Entry", je.name, DP, KAS_KECIL)
		self.assertEqual(result["updated"], 1)
		je.reload()
		self.assertEqual({r.account for r in je.accounts}, {KAS_KECIL, SALES})
		self.assertEqual(_live_gl_accounts("Journal Entry", je.name), {KAS_KECIL, SALES})

	def test_invoice_party_account_is_corrected(self):
		si = self._invoice()

		out = preview("Sales Invoice", si.name, DEBTORS, DEBTORS_2)
		self.assertIsNone(out["error"])
		self.assertTrue(out["warning"])

		apply("Sales Invoice", si.name, DEBTORS, DEBTORS_2)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "debit_to"), DEBTORS_2)
		self.assertEqual(_live_gl_accounts("Sales Invoice", si.name), {DEBTORS_2, SALES})
		self.assertEqual(
			set(
				frappe.get_all(
					"Payment Ledger Entry", filters={"voucher_no": si.name, "delinked": 0}, pluck="account"
				)
			),
			{DEBTORS_2},
		)

	def test_party_and_plain_accounts_do_not_mix(self):
		si = self._invoice()
		self.assertTrue(preview("Sales Invoice", si.name, DEBTORS, KAS_KECIL)["error"])
		self.assertTrue(preview("Sales Invoice", si.name, SALES, DEBTORS_2)["error"])
		with self.assertRaises(frappe.ValidationError):
			apply("Sales Invoice", si.name, DEBTORS, KAS_KECIL)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "debit_to"), DEBTORS)

	def test_cost_center_is_corrected(self):
		cc = f"BAC CC 2 - {ABBR}"
		if not frappe.db.exists("Cost Center", cc):
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "BAC CC 2",
					"company": CHILD_A,
					"parent_cost_center": frappe.db.get_value(
						"Cost Center", {"company": CHILD_A, "is_group": 1}, "name"
					),
				}
			).insert()
		si = self._invoice()

		apply("Sales Invoice", si.name, MAIN_CC, cc, link_doctype="Cost Center")
		si.reload()
		self.assertEqual(si.cost_center, cc)
		self.assertEqual(si.items[0].cost_center, cc)
		self.assertEqual(
			set(
				frappe.get_all(
					"GL Entry",
					filters={"voucher_no": si.name, "is_cancelled": 0, "account": SALES},
					pluck="cost_center",
				)
			),
			{cc},
		)

	def test_closed_period_and_draft_are_refused(self):
		posting_date = add_days(today(), -45)
		je = self._journal(DP, posting_date=posting_date)
		frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": f"BAC Closed {frappe.generate_hash(length=6)}",
				"company": CHILD_A,
				"start_date": posting_date,
				"end_date": posting_date,
				"closed_documents": [{"document_type": "Journal Entry", "closed": 1}],
			}
		).insert()
		self.assertTrue(get_values("Journal Entry", je.name)["blocked"])
		with self.assertRaises(frappe.ValidationError):
			apply("Journal Entry", je.name, DP, KAS_KECIL)
		self.assertEqual(_live_gl_accounts("Journal Entry", je.name), {DP, SALES})

		draft = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": CHILD_A,
				"posting_date": today(),
				"accounts": [
					{"account": DP, "debit_in_account_currency": 10, "cost_center": MAIN_CC},
					{"account": SALES, "credit_in_account_currency": 10, "cost_center": MAIN_CC},
				],
			}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			get_values("Journal Entry", draft.name)
