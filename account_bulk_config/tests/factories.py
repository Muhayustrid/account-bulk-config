"""Test world and data factories for account_bulk_config."""

import frappe

PARENT = "BAC Parent"
PARENT_ABBR = "BACP"
CHILD_A = "BAC Child A"
CHILD_A_ABBR = "BACPA"
CHILD_B = "BAC Child B"
CHILD_B_ABBR = "BACB"

ITEM_1 = "BAC-ITEM-1"
ITEM_2 = "BAC-ITEM-2"
ITEM_GROUP = "BAC Group"


def _setup_company(
	company_name: str, abbr: str, is_group: int = 0, parent_company: str | None = None
) -> None:
	if not frappe.db.exists("Company", company_name):
		doc = {
			"doctype": "Company",
			"company_name": company_name,
			"abbr": abbr,
			"default_currency": "IDR",
			"country": "Indonesia",
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": "Standard",
			"is_group": is_group,
		}
		if parent_company:
			doc["parent_company"] = parent_company
		frappe.get_doc(doc).insert()
		frappe.db.commit()


def setup_world() -> None:
	"""Idempotent test world setup for bulk account configuration."""
	# Ensure parent company exists first
	_setup_company(PARENT, PARENT_ABBR, is_group=1)

	# Ensure child companies exist
	_setup_company(CHILD_A, CHILD_A_ABBR, parent_company=PARENT)
	_setup_company(CHILD_B, CHILD_B_ABBR, parent_company=PARENT)

	# Ensure UOM exists
	if not frappe.db.exists("UOM", "Nos"):
		frappe.get_doc(
			{
				"doctype": "UOM",
				"uom_name": "Nos",
				"must_be_whole_number": 0,
			}
		).insert()

	# Ensure root Item Group exists
	if not frappe.db.exists("Item Group", "All Item Groups"):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "All Item Groups",
				"is_group": 1,
			}
		).insert()

	# Ensure BAC Group exists
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": ITEM_GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert()

	# Ensure Items exist
	for code in (ITEM_1, ITEM_2):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": ITEM_GROUP,
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()

	frappe.db.commit()


def acct(account_name: str, company: str) -> str:
	"""Return the leaf Account name for the given account_name in company."""
	name = frappe.db.get_value(
		"Account",
		{"account_name": account_name, "company": company, "is_group": 0},
		"name",
	)
	if not name:
		abbr = frappe.db.get_value("Company", company, "abbr")
		name = f"{account_name} - {abbr}"
	return name


def make_user_with_roles(email: str, roles: list[str]) -> str:
	"""Create or update a test user with the specified roles and return email."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)

	user.set("roles", [])
	for role in roles:
		if frappe.db.exists("Role", role):
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.clear_cache(user=email)
	frappe.db.commit()
	return email
