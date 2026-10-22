app_name = "account_bulk_config"
app_title = "Bulk Account Config"
app_publisher = "Rotiri Project"
app_description = "Bulk configuration for company default accounts and item defaults."
app_email = "rotiropi@users.noreply.github.com"
app_license = "mit"

required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "account_bulk_config",
		"logo": "/assets/account_bulk_config/images/logo.svg",
		"title": "Bulk Account Config",
		"route": "/desk/bulk-account-config",
		"has_permission": "account_bulk_config.api.permission.has_app_permission",
	}
]
