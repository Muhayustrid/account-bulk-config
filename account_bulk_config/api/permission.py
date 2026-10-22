import frappe

APP_ROLES = {"System Manager", "Accounts Manager", "Item Manager"}


def has_app_permission() -> bool:
	"""Gate the apps-screen tile to the roles that can open the bulk pages."""
	return bool(APP_ROLES & set(frappe.get_roles()))
