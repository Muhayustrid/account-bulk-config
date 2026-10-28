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

# "Koreksi Akun" on submitted vouchers that Repost Accounting Ledger can repost
doctype_js = {
	dt: "public/js/voucher_account_fix.js"
	for dt in ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Purchase Receipt")
}

app_include_js = "coa_sync.bundle.js"

doctype_tree_js = {"Account": "public/js/account_tree.js"}

# rename an account in a parent company without renaming every child's copy in the same request
override_whitelisted_methods = {
	"erpnext.accounts.doctype.account.account.update_account_number": (
		"account_bulk_config.api.coa_sync.update_account_number"
	),
}

doc_events = {
	"Account": {
		"before_validate": "account_bulk_config.api.coa_sync.before_validate",
		"on_update": "account_bulk_config.api.coa_sync.on_update",
	}
}
