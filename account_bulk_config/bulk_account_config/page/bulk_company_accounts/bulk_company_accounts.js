// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

{% include "account_bulk_config/public/js/bulk_grid.js" %}

frappe.pages["bulk-company-accounts"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk Company Accounts"),
		single_column: true,
	});
	wrapper.bulk_company_accounts = new BulkCompanyAccountsPage(page);
};

frappe.pages["bulk-company-accounts"].on_page_show = function (wrapper) {
	if (
		wrapper.bulk_company_accounts &&
		wrapper.bulk_company_accounts.grid &&
		wrapper.bulk_company_accounts.grid.state
	) {
		wrapper.bulk_company_accounts.grid.refresh();
	}
};

class BulkCompanyAccountsPage {
	constructor(page) {
		this.page = page;
		this._setup_filters();
		this._setup_grid();
		this.grid.refresh();
	}

	_later(fn) {
		return () => setTimeout(fn, 0);
	}

	_setup_filters() {
		this.parent_company_field = this.page.add_field({
			fieldname: "parent_company",
			label: __("Parent Company"),
			fieldtype: "Link",
			options: "Company",
			change: this._later(() => {
				this.grid.confirm_dirty(() => {
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});

		this.search_field = this.page.add_field({
			fieldname: "search",
			label: __("Cari"),
			fieldtype: "Data",
			placeholder: __("Cari company/abbr"),
			change: frappe.utils.debounce(
				this._later(() => {
					this.grid.confirm_dirty(() => {
						this.grid.start = 0;
						this.grid.refresh();
					});
				}),
				300
			),
		});

		this.column_groups_field = this.page.add_field({
			fieldname: "column_groups",
			label: __("Kelompok kolom"),
			fieldtype: "MultiSelectList",
			options: [
				{ label: __("Inti akuntansi"), value: "core", description: "" },
				{ label: __("Stok & manufaktur"), value: "stock", description: "" },
				{ label: __("Uang muka, kurs, beban beli"), value: "advance", description: "" },
				{ label: __("Aset & deferred"), value: "asset", description: "" },
			],
			change: this._later(() => {
				this.grid._render();
			}),
		});
	}

	_get_key_columns() {
		return [
			{
				id: "name",
				name: __("Company"),
				sticky: true,
				editable: false,
				sortable: false,
				dropdown: false,
				focusable: false,
				width: 260,
				format: (value, row, column, data) => {
					const r = data || row;
					const indent = (r.indent || 0) * 16;
					const groupIcon = r.is_group ? `<span class="bac-tree-icon mr-1">▸</span>` : "";
					const childPill = r.child_count
						? `<span class="indicator-pill gray ml-1">${r.child_count}</span>`
						: "";
					const link = `<a href="/app/company/${encodeURIComponent(value)}" class="ellipsis font-weight-bold" title="${frappe.utils.escape_html(value)}">${frappe.utils.escape_html(value)}</a>`;
					return `<div style="padding-left: ${indent}px; display: flex; align-items: center;">${groupIcon}${link}${childPill}</div>`;
				},
			},
			{
				id: "abbr",
				name: __("Abbr"),
				sticky: true,
				editable: false,
				sortable: false,
				dropdown: false,
				focusable: false,
				width: 80,
				format: (value) => frappe.utils.escape_html(value || ""),
			},
		];
	}

	_setup_grid() {
		this.grid = new BulkGrid({
			page: this.page,
			target: "company",
			key_columns: () => this._get_key_columns(),
			get_rows: {
				method: "account_bulk_config.api.company_accounts.get_rows",
				args: () => ({
					parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
					search: this.search_field ? (this.search_field.get_value() || "").trim() : null,
				}),
			},
			get_column_groups: () => {
				const val = this.column_groups_field ? this.column_groups_field.get_value() : null;
				// no group picked = show every group, so no column is silently hidden
				return val && (Array.isArray(val) ? val.length : val) ? val : this.column_groups_field.df.options.map((o) => o.value);
			},
			get_export_filters: () => ({
				parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
				search: this.search_field ? (this.search_field.get_value() || "").trim() : null,
			}),
		});
		this.page.add_menu_item(__("Salin COA ke Anak Perusahaan…"), () =>
			account_bulk_config.coa_sync_dialog(this.parent_company_field.get_value())
		);
	}
}
