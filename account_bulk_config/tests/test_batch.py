from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from account_bulk_config.api.batch import apply_changes, run_job, save_changes
from account_bulk_config.api.company_accounts import get_rows
from account_bulk_config.tests.factories import (
	CHILD_A,
	CHILD_B,
	PARENT,
	acct,
	make_user_with_roles,
	setup_world,
)


class TestBatch(IntegrationTestCase):
	def setUp(self):
		setup_world()

	def _chg(self, company, field, new):
		return {
			"name": company,
			"company": company,
			"field": field,
			"old": frappe.db.get_value("Company", company, field),
			"new": new,
		}

	def test_one_error_does_not_block_others(self):
		res = apply_changes(
			"company",
			[
				self._chg(CHILD_A, "default_income_account", acct("Sales", CHILD_A)),
				self._chg(CHILD_B, "default_income_account", acct("Sales", CHILD_A)),  # wrong company
			],
		)
		by = {r["company"]: r for r in res}
		self.assertEqual(by[CHILD_A]["status"], "ok")
		self.assertEqual(by[CHILD_B]["status"], "error")
		self.assertEqual(
			frappe.db.get_value("Company", CHILD_A, "default_income_account"), acct("Sales", CHILD_A)
		)

	def test_stale_old_is_skipped(self):
		c = self._chg(CHILD_A, "default_income_account", acct("Sales", CHILD_A))
		c["old"] = "Something Else - BACPA"
		self.assertEqual(apply_changes("company", [c])[0]["status"], "skipped")

	def test_unknown_field_rejected(self):
		c = self._chg(CHILD_A, "abbr", "HACK")
		self.assertEqual(apply_changes("company", [c])[0]["status"], "error")
		self.assertEqual(frappe.db.get_value("Company", CHILD_A, "abbr"), "BACPA")

	def test_result_reports_saved_value(self):
		res = apply_changes("company", [self._chg(CHILD_A, "default_cash_account", None)])
		self.assertEqual(
			res[0]["values"]["default_cash_account"],
			frappe.db.get_value("Company", CHILD_A, "default_cash_account"),
		)

	def test_no_write_permission(self):
		user = make_user_with_roles("bac-nowrite@example.com", ["Accounts User"])
		with self.set_user(user):
			res = apply_changes(
				"company", [self._chg(CHILD_A, "default_income_account", acct("Sales", CHILD_A))]
			)
		self.assertEqual(res[0]["status"], "error")

	def test_get_rows_tree(self):
		out = get_rows(parent_company=PARENT)
		self.assertEqual(out["rows"][0]["name"], PARENT)
		self.assertEqual(out["total"], 3)
		self.assertEqual(out["rows"][0]["child_count"], 2)

	def test_save_changes_validates_target_upfront(self):
		changes = [
			{"name": f"Doc {i}", "company": CHILD_A, "field": "abbr", "old": None, "new": None}
			for i in range(25)
		]
		with self.assertRaises(frappe.ValidationError):
			save_changes("invalid_target", changes)

	@patch("account_bulk_config.api.batch.frappe.publish_realtime")
	@patch("account_bulk_config.api.batch.frappe.enqueue")
	def test_save_changes_enqueues_and_run_job_receives_job_id(self, mock_enqueue, mock_publish):
		changes = [
			{"name": f"Doc {i}", "company": CHILD_A, "field": "abbr", "old": None, "new": None}
			for i in range(25)
		]
		res = save_changes("company", changes)
		self.assertIn("job_id", res)
		returned_job_id = res["job_id"]

		mock_enqueue.assert_called_once()
		enqueue_kwargs = mock_enqueue.call_args.kwargs
		self.assertEqual(enqueue_kwargs.get("job_id"), returned_job_id)
		self.assertEqual(enqueue_kwargs.get("bac_job_id"), returned_job_id)

		run_job(
			target=enqueue_kwargs["target"],
			changes=[],
			user=enqueue_kwargs["user"],
			bac_job_id=enqueue_kwargs.get("bac_job_id"),
		)
		mock_publish.assert_called_once()
		event_name, event_data = mock_publish.call_args[0]
		self.assertEqual(event_name, "bulk_account_config_done")
		self.assertEqual(event_data.get("job_id"), returned_job_id)
