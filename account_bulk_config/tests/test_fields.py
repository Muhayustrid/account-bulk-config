import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.fields import (
	COMPANY_FIELDS,
	ITEM_DEFAULT_FIELDS,
	validate_link,
)
from account_bulk_config.tests.factories import CHILD_A, CHILD_B, acct, setup_world


class TestFields(IntegrationTestCase):
	def test_field_lists_match_doctypes(self):
		company_links = {
			f.fieldname
			for f in frappe.get_meta("Company").fields
			if f.fieldtype == "Link" and f.options in ("Account", "Cost Center", "Warehouse")
		}
		self.assertEqual({f["fieldname"] for f in COMPANY_FIELDS}, company_links)
		self.assertEqual(len(COMPANY_FIELDS), len(company_links))
		item_fields = {
			f.fieldname
			for f in frappe.get_meta("Item Default").fields
			if f.fieldtype == "Link" and f.fieldname != "company"
		}
		self.assertEqual({f["fieldname"] for f in ITEM_DEFAULT_FIELDS}, item_fields)

	def test_validate_link(self):
		setup_world()
		fdef = next(f for f in COMPANY_FIELDS if f["fieldname"] == "default_receivable_account")
		ok = acct("Debtors", CHILD_A)
		self.assertIsNone(validate_link(fdef, ok, CHILD_A))
		self.assertIsNone(validate_link(fdef, None, CHILD_A))
		self.assertIn(CHILD_A, validate_link(fdef, acct("Debtors", CHILD_B), CHILD_A))  # wrong company
		self.assertIsNotNone(validate_link(fdef, acct("Sales", CHILD_A), CHILD_A))  # wrong account_type
		self.assertIsNotNone(validate_link(fdef, "Accounts Receivable - BACPA", CHILD_A))  # group
