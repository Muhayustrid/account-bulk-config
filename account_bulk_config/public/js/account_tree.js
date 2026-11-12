// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

// Chart of Accounts tree menu; the dialog itself lives in coa_sync.bundle.js
(() => {
	const tree = frappe.treeview_settings && frappe.treeview_settings["Account"];
	if (tree && !(tree.menu_items || []).some((m) => m.bac_coa_sync)) {
		tree.menu_items = tree.menu_items || [];
		tree.menu_items.push({
			bac_coa_sync: 1,
			label: __("Salin COA ke Anak / Company Lain…"),
			condition: () => frappe.model.can_create("Account"),
			action: () => {
				const page =
					frappe.treeview_settings["Account"].treeview && frappe.treeview_settings["Account"].treeview.page;
				account_bulk_config.coa_sync_dialog(
					page && page.fields_dict.company && page.fields_dict.company.get_value(),
				);
			},
		});
	}
})();
