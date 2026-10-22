// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

{% include "account_bulk_config/public/js/bulk_grid.js" %}

frappe.pages["bulk-mode-of-payment"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk Mode of Payment"),
		single_column: true,
	});
	wrapper.bulk_mode_of_payment = new BulkModeOfPaymentPage(page);
};

frappe.pages["bulk-mode-of-payment"].on_page_show = function (wrapper) {
	if (
		wrapper.bulk_mode_of_payment &&
		wrapper.bulk_mode_of_payment.grid &&
		wrapper.bulk_mode_of_payment.grid.state
	) {
		wrapper.bulk_mode_of_payment.grid.refresh();
	}
};

class BulkModeOfPaymentPage {
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
		this.mode_of_payment_field = this.page.add_field({
			fieldname: "mode_of_payment",
			label: __("Mode of Payment"),
			fieldtype: "Link",
			options: "Mode of Payment",
			get_query: () => ({ filters: { enabled: 1 } }),
			change: this._later(() => {
				this.grid.confirm_dirty(() => {
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});

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

		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			change: this._later(() => {
				this.grid.confirm_dirty(() => {
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});
	}

	_get_key_columns() {
		return [
			{
				id: "name",
				name: __("Mode of Payment"),
				sticky: true,
				editable: false,
				sortable: false,
				dropdown: false,
				focusable: false,
				width: 220,
				format: (value, row, column, data) => {
					const r = data || row;
					const newBadge = r.is_new
						? `<span class="badge badge-warning ml-1" style="font-size: 10px;">${__("Baru")}</span>`
						: "";
					const label = (r && r.label) || value;
					const link = `<a href="/app/mode-of-payment/${encodeURIComponent(value)}" class="ellipsis font-weight-bold" title="${frappe.utils.escape_html(value)}">${frappe.utils.escape_html(label)}</a>`;
					const code = label !== value ? `<div class="bac-sub ellipsis">${frappe.utils.escape_html(value)}</div>` : "";
					return `<div style="display: flex; align-items: center;"><div style="min-width: 0;">${link}${code}</div>${newBadge}</div>`;
				},
			},
			{
				id: "company",
				name: __("Company"),
				sticky: true,
				editable: false,
				sortable: false,
				dropdown: false,
				focusable: false,
				width: 200,
				format: (value, row, column, data) => {
					const r = data || row;
					const groupIcon = r.company_is_group ? `<span class="bac-tree-icon mr-1">▸</span>` : "";
					const link = `<a href="/app/company/${encodeURIComponent(value)}" class="ellipsis" title="${frappe.utils.escape_html(value)}">${frappe.utils.escape_html(value)}</a>`;
					return `<div style="display: flex; align-items: center;">${groupIcon}${link}</div>`;
				},
			},
		];
	}

	_setup_grid() {
		this.grid = new BulkGrid({
			page: this.page,
			target: "mode_of_payment",
			key_columns: () => this._get_key_columns(),
			get_rows: {
				method: "account_bulk_config.api.mode_of_payment.get_rows",
				args: () => ({
					mode_of_payment: this.mode_of_payment_field ? this.mode_of_payment_field.get_value() : null,
					parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
					company: this.company_field ? this.company_field.get_value() : null,
				}),
			},
			get_column_groups: () => ["core"],
			get_export_filters: () => ({
				mode_of_payment: this.mode_of_payment_field ? this.mode_of_payment_field.get_value() : null,
				parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
				company: this.company_field ? this.company_field.get_value() : null,
			}),
		});
	}
}
