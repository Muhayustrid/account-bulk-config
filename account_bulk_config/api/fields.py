"""Metadata and validation for bulk account configuration fields."""

import frappe

COMPANY_SCOPED = {"Account", "Cost Center", "Warehouse"}

COMPANY_FIELDS = [
	{
		"fieldname": "default_warehouse_for_sales_return",
		"label": "Default Warehouse for Sales Return",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
	{
		"fieldname": "default_bank_account",
		"label": "Default Bank Account",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": "Bank"},
	},
	{
		"fieldname": "default_cash_account",
		"label": "Default Cash Account",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": "Cash"},
	},
	{
		"fieldname": "default_receivable_account",
		"label": "Default Receivable Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Asset", "account_type": "Receivable"},
	},
	{
		"fieldname": "round_off_account",
		"label": "Round Off Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": ["in", ["Expense", "Income"]]},
	},
	{
		"fieldname": "round_off_cost_center",
		"label": "Round Off Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "write_off_account",
		"label": "Write Off Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "exchange_gain_loss_account",
		"label": "Exchange Gain / Loss Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": ["in", ["Expense", "Income"]]},
	},
	{
		"fieldname": "unrealized_exchange_gain_loss_account",
		"label": "Unrealized Exchange Gain/Loss Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": ["in", ["Expense", "Income", "Equity", "Liability"]]},
	},
	{
		"fieldname": "default_payable_account",
		"label": "Default Payable Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Liability", "account_type": "Payable"},
	},
	{
		"fieldname": "default_expense_account",
		"label": "Default Cost of Goods Sold Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "default_income_account",
		"label": "Default Income Account",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Income"},
	},
	{
		"fieldname": "default_deferred_revenue_account",
		"label": "Default Deferred Revenue Account",
		"link": "Account",
		"group": "asset",
		"filters": {},
	},
	{
		"fieldname": "default_deferred_expense_account",
		"label": "Default Deferred Expense Account",
		"link": "Account",
		"group": "asset",
		"filters": {},
	},
	{
		"fieldname": "cost_center",
		"label": "Default Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "default_inventory_account",
		"label": "Default Inventory Account",
		"link": "Account",
		"group": "stock",
		"filters": {"account_type": "Stock"},
	},
	{
		"fieldname": "stock_adjustment_account",
		"label": "Stock Adjustment Account",
		"link": "Account",
		"group": "stock",
		"filters": {"root_type": "Expense", "account_type": "Stock Adjustment"},
	},
	{
		"fieldname": "stock_received_but_not_billed",
		"label": "Stock Received But Not Billed",
		"link": "Account",
		"group": "stock",
		"filters": {"root_type": "Liability", "account_type": "Stock Received But Not Billed"},
	},
	{
		"fieldname": "accumulated_depreciation_account",
		"label": "Accumulated Depreciation Account",
		"link": "Account",
		"group": "asset",
		"filters": {"root_type": "Asset", "account_type": "Accumulated Depreciation"},
	},
	{
		"fieldname": "depreciation_expense_account",
		"label": "Depreciation Expense Account",
		"link": "Account",
		"group": "asset",
		"filters": {"root_type": "Expense", "account_type": "Depreciation"},
	},
	{
		"fieldname": "disposal_account",
		"label": "Gain/Loss Account on Asset Disposal",
		"link": "Account",
		"group": "asset",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "depreciation_cost_center",
		"label": "Asset Depreciation Cost Center",
		"link": "Cost Center",
		"group": "asset",
		"filters": {},
	},
	{
		"fieldname": "capital_work_in_progress_account",
		"label": "Capital Work In Progress Account",
		"link": "Account",
		"group": "asset",
		"filters": {"account_type": "Capital Work in Progress"},
	},
	{
		"fieldname": "asset_received_but_not_billed",
		"label": "Asset Received But Not Billed",
		"link": "Account",
		"group": "asset",
		"filters": {"account_type": "Asset Received But Not Billed"},
	},
	{
		"fieldname": "default_in_transit_warehouse",
		"label": "Default In-Transit Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {"warehouse_type": "Transit"},
	},
	{
		"fieldname": "default_warehouse",
		"label": "Default Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
	{
		"fieldname": "sample_retention_warehouse",
		"label": "Sample Retention Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
	{
		"fieldname": "unrealized_profit_loss_account",
		"label": "Unrealized Profit / Loss Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": ["in", ["Liability", "Asset"]]},
	},
	{
		"fieldname": "default_discount_account",
		"label": "Default Payment Discount Account",
		"link": "Account",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "default_provisional_account",
		"label": "Default Provisional Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": ["in", ["Liability", "Asset"]]},
	},
	{
		"fieldname": "default_advance_received_account",
		"label": "Default Advance Received Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": "Liability", "account_type": "Receivable"},
	},
	{
		"fieldname": "default_advance_paid_account",
		"label": "Default Advance Paid Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": "Asset", "account_type": "Payable"},
	},
	{
		"fieldname": "expenses_added_to_stock_account",
		"label": "Expenses Added To Stock Account",
		"link": "Account",
		"group": "stock",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "expenses_added_to_stock_contra_account",
		"label": "Expenses Added To Stock Contra Account",
		"link": "Account",
		"group": "stock",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "default_operating_cost_account",
		"label": "Default Operating Cost Account",
		"link": "Account",
		"group": "stock",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "round_off_for_opening",
		"label": "Round Off for Opening",
		"link": "Account",
		"group": "core",
		"filters": {"root_type": "Liability", "account_type": "Round Off for Opening"},
	},
	{
		"fieldname": "purchase_expense_account",
		"label": "Purchase Expense Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "purchase_expense_contra_account",
		"label": "Purchase Expense Contra Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "service_expense_account",
		"label": "Service Expense Account",
		"link": "Account",
		"group": "advance",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "default_wip_warehouse",
		"label": "Default Work In Progress Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
	{
		"fieldname": "default_fg_warehouse",
		"label": "Default Finished Goods Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
	{
		"fieldname": "default_scrap_warehouse",
		"label": "Default Scrap Warehouse",
		"link": "Warehouse",
		"group": "stock",
		"filters": {},
	},
]

ITEM_DEFAULT_FIELDS = [
	{
		"fieldname": "default_warehouse",
		"label": "Default Warehouse",
		"link": "Warehouse",
		"group": "stock_price",
		"filters": {},
	},
	{
		"fieldname": "default_price_list",
		"label": "Default Price List",
		"link": "Price List",
		"group": "stock_price",
		"filters": {},
	},
	{
		"fieldname": "buying_cost_center",
		"label": "Default Buying Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "default_supplier",
		"label": "Default Supplier",
		"link": "Supplier",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "expense_account",
		"label": "Default Expense Account",
		"link": "Account",
		"group": "core",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "selling_cost_center",
		"label": "Default Selling Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "income_account",
		"label": "Default Income Account",
		"link": "Account",
		"group": "core",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "default_discount_account",
		"label": "Default Discount Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "default_provisional_account",
		"label": "Default Provisional Account (Service)",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": ["in", ["Liability", "Asset"]]},
	},
	{
		"fieldname": "deferred_expense_account",
		"label": "Deferred Expense Account",
		"link": "Account",
		"group": "deferred",
		"filters": {"root_type": "Asset"},
	},
	{
		"fieldname": "deferred_revenue_account",
		"label": "Deferred Revenue Account",
		"link": "Account",
		"group": "deferred",
		"filters": {"root_type": "Liability"},
	},
	{
		"fieldname": "default_cogs_account",
		"label": "Default COGS Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "purchase_expense_account",
		"label": "Purchase Expense Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "purchase_expense_contra_account",
		"label": "Purchase Expense Contra Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "expenses_added_to_stock_account",
		"label": "Expenses Added To Stock Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "expenses_added_to_stock_contra_account",
		"label": "Expenses Added To Stock Contra Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"root_type": "Expense"},
	},
	{
		"fieldname": "default_inventory_account",
		"label": "Default Inventory Account",
		"link": "Account",
		"group": "advanced",
		"filters": {"account_type": "Stock"},
	},
	{
		"fieldname": "inventory_account_currency",
		"label": "Inventory Account Currency",
		"link": "Currency",
		"group": "advanced",
		"filters": {},
		"read_only": 1,
	},
]

MOP_FIELDS = [
	{
		"fieldname": "default_account",
		"label": "Default Account",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": ["in", ["Bank", "Cash", "Receivable"]]},
	},
]


# filters mirror the set_query of erpnext's pos_profile.js
POS_PROFILE_FIELDS = [
	{
		"fieldname": "warehouse",
		"label": "Warehouse",
		"link": "Warehouse",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "income_account",
		"label": "Income Account",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": "Income Account"},
	},
	{
		"fieldname": "expense_account",
		"label": "Expense Account",
		"link": "Account",
		"group": "core",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "cost_center",
		"label": "Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
	{
		"fieldname": "account_for_change_amount",
		"label": "Account for Change Amount",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": ["in", ["Cash", "Bank"]]},
	},
	{
		"fieldname": "write_off_account",
		"label": "Write Off Account",
		"link": "Account",
		"group": "core",
		"filters": {"report_type": "Profit and Loss"},
	},
	{
		"fieldname": "write_off_cost_center",
		"label": "Write Off Cost Center",
		"link": "Cost Center",
		"group": "core",
		"filters": {},
	},
]


# filters mirror the set_query of erpnext's warehouse.js
WAREHOUSE_FIELDS = [
	{
		"fieldname": "account",
		"label": "Account",
		"link": "Account",
		"group": "core",
		"filters": {"account_type": "Stock"},
	},
]


@frappe.whitelist()
def get_field_meta(target: str) -> list[dict]:
	"""Return column metadata for the given target (company, item, item_group, mode_of_payment, pos_profile, warehouse)."""
	if target == "company":
		return COMPANY_FIELDS
	if target in ("item", "item_group"):
		return ITEM_DEFAULT_FIELDS
	if target == "mode_of_payment":
		return MOP_FIELDS
	if target == "pos_profile":
		return POS_PROFILE_FIELDS
	if target == "warehouse":
		return WAREHOUSE_FIELDS
	frappe.throw(f"Invalid target: {target}")


def validate_link(fdef: dict, value: str | None, company: str) -> str | None:
	"""Validate that value satisfies the link field definition for the given company.

	Returns None if valid or empty, otherwise returns an error message.
	"""
	if not value:
		return None

	doctype = fdef.get("link")
	if not doctype or not frappe.db.exists(doctype, value):
		return f"{doctype} {value} does not exist"

	meta = frappe.get_meta(doctype)
	fields_to_get = ["name"]
	for col in ("company", "is_group", "disabled", "enabled"):
		if meta.has_field(col):
			fields_to_get.append(col)

	for k in fdef.get("filters", {}):
		if meta.has_field(k) and k not in fields_to_get:
			fields_to_get.append(k)

	doc = frappe.db.get_value(doctype, value, fields_to_get, as_dict=True)
	if not doc:
		return f"{doctype} {value} does not exist"

	if meta.has_field("company") and doc.get("company") != company:
		return f"{doctype} {value} belongs to {doc.get('company')}, not {company}"

	if meta.has_field("is_group") and doc.get("is_group"):
		return f"{doctype} {value} is a group"

	if meta.has_field("disabled") and doc.get("disabled"):
		return f"{doctype} {value} is disabled"

	if meta.has_field("enabled") and not doc.get("enabled"):
		return f"{doctype} {value} is disabled"

	for k, expected in fdef.get("filters", {}).items():
		actual = doc.get(k)
		if isinstance(expected, (list, tuple)) and expected and expected[0] == "in":
			if actual not in expected[1]:
				return f"{doctype} {value} has {k}={actual}, expected one of {expected[1]}"
		elif actual != expected:
			return f"{doctype} {value} has {k}={actual}, expected {expected}"

	return None
