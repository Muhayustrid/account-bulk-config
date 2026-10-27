"""Tests for carrying a changed default over to submitted documents."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from account_bulk_config.api.ledger_update import apply_changes, get_current_value, preview
from account_bulk_config.tests.factories import CHILD_A, ITEM_1, make_user_with_roles, setup_world

ABBR = "BACPA"
DP = f"BAC DP Penjualan - {ABBR}"
KAS_KECIL = f"BAC Kas Kecil - {ABBR}"
DEBTORS = f"Debtors - {ABBR}"
DEBTORS_2 = f"BAC Debtors 2 - {ABBR}"
SALES = f"Sales - {ABBR}"
MAIN_CC = f"Main - {ABBR}"
CUSTOMER = "BAC Ledger Customer"


def _account(account_name, account_type, parent_name):
	name = f"{account_name} - {ABBR}"
	if not frappe.db.exists("Account", name):
		parent = frappe.db.get_value(
			"Account", {"account_name": parent_name, "company": CHILD_A, "is_group": 1}, "name"
		)
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"company": CHILD_A,
				"parent_account": parent,
				"account_type": account_type,
			}
		)
		# BAC Child A has a parent company; these accounts exist in the child only
		doc.flags.ignore_root_company_validation = True
		doc.insert()
	return name


def _live_gl_accounts(voucher_type, voucher_no):
	return set(
		frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
			pluck="account",
		)
	)


def _change(field, old, new, name):
	return {"name": name, "company": CHILD_A, "field": field, "old": old, "new": new}


class TestLedgerUpdate(IntegrationTestCase):
	def setUp(self):
		setup_world()
		_account("BAC DP Penjualan", "Cash", "Cash In Hand")
		_account("BAC Kas Kecil", "Cash", "Cash In Hand")
		_account("BAC Debtors 2", "Receivable", "Accounts Receivable")
		# setup_world commits, so a period closed by an earlier run would still be there
		for name in frappe.get_all(
			"Accounting Period",
			filters={"company": CHILD_A, "period_name": ["like", "BAC Closed%"]},
			pluck="name",
		):
			frappe.delete_doc("Accounting Period", name)
		frappe.db.set_value(
			"Company", CHILD_A, {"round_off_account": f"Round Off - {ABBR}", "round_off_cost_center": MAIN_CC}
		)
		# a fresh one per test: the test world is committed, so documents of earlier runs remain
		self.mop = frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": f"BAC Ledger MoP {frappe.generate_hash(length=8)}",
				"type": "Cash",
				"enabled": 1,
			}
		).insert()
		if not frappe.db.exists("Customer", CUSTOMER):
			frappe.get_doc({"doctype": "Customer", "customer_name": CUSTOMER}).insert()

	def _journal(self, account, mode_of_payment=None, posting_date=None):
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": CHILD_A,
				"posting_date": posting_date or today(),
				"mode_of_payment": mode_of_payment,
				"accounts": [
					{"account": account, "debit_in_account_currency": 100, "cost_center": MAIN_CC},
					{"account": SALES, "credit_in_account_currency": 100, "cost_center": MAIN_CC},
				],
			}
		)
		je.insert()
		je.submit()
		return je

	def _payment(self, paid_to, mode_of_payment):
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": CHILD_A,
				"posting_date": today(),
				"party_type": "Customer",
				"party": CUSTOMER,
				"paid_from": DEBTORS,
				"paid_to": paid_to,
				"mode_of_payment": mode_of_payment,
				"paid_amount": 50,
				"received_amount": 50,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
			}
		)
		pe.insert()
		pe.submit()
		return pe

	def _invoice(self):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": CHILD_A,
				"customer": CUSTOMER,
				"posting_date": today(),
				"due_date": today(),
				"currency": "IDR",
				"debit_to": DEBTORS,
				"cost_center": MAIN_CC,
				"items": [
					{
						"item_code": ITEM_1,
						"qty": 1,
						"rate": 100,
						"income_account": SALES,
						"cost_center": MAIN_CC,
					}
				],
			}
		)
		si.insert()
		si.submit()
		return si

	def test_mode_of_payment_account_moves_on_its_documents_only(self):
		je = self._journal(DP, mode_of_payment=self.mop.name)
		pe = self._payment(DP, self.mop.name)
		other = self._journal(DP)  # same account, no mode of payment: not this setting's

		rows = preview("mode_of_payment", [_change("default_account", DP, KAS_KECIL, self.mop.name)])
		self.assertEqual(rows[0]["count"], 2)
		self.assertEqual(
			{(v["voucher_type"], v["voucher_no"]) for v in rows[0]["vouchers"]},
			{("Journal Entry", je.name), ("Payment Entry", pe.name)},
		)

		[result] = apply_changes(
			"mode_of_payment", [_change("default_account", DP, KAS_KECIL, self.mop.name)]
		)
		self.assertEqual(result["status"], "ok", result)
		self.assertEqual(result["updated"], 2)
		self.assertEqual(result["reposts"][0]["doctype"], "Repost Accounting Ledger")

		je.reload()
		self.assertEqual({r.account for r in je.accounts}, {KAS_KECIL, SALES})
		self.assertEqual(_live_gl_accounts("Journal Entry", je.name), {KAS_KECIL, SALES})
		self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "paid_to"), KAS_KECIL)
		self.assertEqual(_live_gl_accounts("Payment Entry", pe.name), {KAS_KECIL, DEBTORS})

		self.assertEqual(_live_gl_accounts("Journal Entry", other.name), {DP, SALES})
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_doctype": "Journal Entry", "reference_name": je.name, "comment_type": "Info"},
			)
		)

	def test_company_receivable_moves_invoice_and_payment_ledger(self):
		si = self._invoice()

		[result] = apply_changes(
			"company", [_change("default_receivable_account", DEBTORS, DEBTORS_2, name=CHILD_A)]
		)
		self.assertEqual(result["status"], "ok", result)

		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "debit_to"), DEBTORS_2)
		self.assertEqual(_live_gl_accounts("Sales Invoice", si.name), {DEBTORS_2, SALES})
		ple_accounts = set(
			frappe.get_all(
				"Payment Ledger Entry",
				filters={"voucher_no": si.name, "delinked": 0},
				pluck="account",
			)
		)
		self.assertEqual(ple_accounts, {DEBTORS_2})

	def test_item_income_account_moves_on_its_rows_only(self):
		new_income = _account("BAC Sales 2", "Income Account", "Direct Income")
		si = self._invoice()

		[result] = apply_changes(
			"item", [_change("income_account", SALES, new_income, name=ITEM_1)], from_date=today()
		)
		self.assertEqual(result["status"], "ok", result)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice Item", {"parent": si.name}, "income_account"), new_income
		)
		self.assertEqual(_live_gl_accounts("Sales Invoice", si.name), {DEBTORS, new_income})

		[row] = preview("item", [_change("income_account", SALES, new_income, name="BAC-ITEM-2")])
		self.assertNotIn(si.name, [v["voucher_no"] for v in row["vouchers"]])

	def test_warehouse_account_reposts_stock_vouchers(self):
		stock_1 = _account("BAC Stock 1", "Stock", "Stock Assets")
		stock_2 = _account("BAC Stock 2", "Stock", "Stock Assets")
		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": f"BAC Ledger WH {frappe.generate_hash(length=6)}",
				"company": CHILD_A,
				"account": stock_1,
			}
		).insert()
		frappe.db.set_value("Company", CHILD_A, "stock_adjustment_account", f"Stock Adjustment - {ABBR}")
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": CHILD_A,
				"items": [
					{
						"item_code": ITEM_1,
						"qty": 1,
						"basic_rate": 100,
						"t_warehouse": warehouse.name,
						"expense_account": f"Stock Adjustment - {ABBR}",
						"cost_center": MAIN_CC,
					}
				],
			}
		)
		se.insert()
		se.submit()
		self.assertIn(stock_1, _live_gl_accounts("Stock Entry", se.name))

		change = _change("account", stock_1, stock_2, name=warehouse.name)
		[row] = preview("warehouse", [change])
		self.assertIn("Simpan dulu", row["error"])

		warehouse.db_set("account", stock_2)
		[result] = apply_changes("warehouse", [change])
		self.assertEqual(result["status"], "ok", result)
		self.assertEqual(result["reposts"][0]["doctype"], "Repost Item Valuation")
		self.assertEqual(_live_gl_accounts("Stock Entry", se.name), {stock_2, f"Stock Adjustment - {ABBR}"})

	def test_closed_accounting_period_is_skipped(self):
		posting_date = add_days(today(), -40)
		je = self._journal(DP, mode_of_payment=self.mop.name, posting_date=posting_date)
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

		[row] = preview("mode_of_payment", [_change("default_account", DP, KAS_KECIL, self.mop.name)])
		self.assertNotIn(je.name, [v["voucher_no"] for v in row["vouchers"]])
		self.assertIn(je.name, [v["voucher_no"] for v in row["skipped"]])

		apply_changes("mode_of_payment", [_change("default_account", DP, KAS_KECIL, self.mop.name)])
		self.assertEqual(_live_gl_accounts("Journal Entry", je.name), {DP, SALES})

	def test_gl_only_rule_needs_saved_setting(self):
		round_off = frappe.db.get_value("Company", CHILD_A, "round_off_account")
		[row] = preview("company", [_change("round_off_account", round_off, SALES, name=CHILD_A)])
		self.assertIn("Simpan dulu", row["error"])

	def test_invalid_new_value_is_rejected(self):
		[row] = preview("mode_of_payment", [_change("default_account", DP, "Cash - BACB", self.mop.name)])
		self.assertTrue(row["error"])
		self.assertEqual(row["count"], 0)

	def test_current_value(self):
		self.mop.append("accounts", {"company": CHILD_A, "default_account": KAS_KECIL})
		self.mop.save()
		self.assertEqual(
			get_current_value("mode_of_payment", self.mop.name, CHILD_A, "default_account"), KAS_KECIL
		)

	def test_needs_repost_permission(self):
		user = make_user_with_roles("bac-ledger-acc@example.com", ["Accounts Manager"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				preview("mode_of_payment", [_change("default_account", DP, KAS_KECIL, self.mop.name)])
		finally:
			frappe.set_user("Administrator")
