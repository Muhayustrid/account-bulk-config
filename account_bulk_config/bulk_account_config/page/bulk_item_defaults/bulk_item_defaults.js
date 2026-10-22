// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

{% include "account_bulk_config/public/js/bulk_grid.js" %}

frappe.pages["bulk-item-defaults"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk Item Defaults"),
		single_column: true,
	});
	wrapper.bulk_item_defaults = new BulkItemDefaultsPage(page);
};

frappe.pages["bulk-item-defaults"].on_page_show = function (wrapper) {
	if (
		wrapper.bulk_item_defaults &&
		wrapper.bulk_item_defaults.grid &&
		wrapper.bulk_item_defaults.grid.state
	) {
		wrapper.bulk_item_defaults.grid.refresh();
	}
};

class BulkItemDefaultsPage {
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
		this.mode_field = this.page.add_field({
			fieldname: "mode",
			label: __("Mode"),
			fieldtype: "Select",
			options: [
				{ label: __("Item Group"), value: "item_group" },
				{ label: __("Item"), value: "item" },
			],
			default: "item_group",
			change: this._later(() => {
				const isItem = this.mode_field.get_value() === "item";
				if (this.item_field && this.item_field.$wrapper) {
					this.item_field.$wrapper.toggle(isItem);
					if (!isItem) this.item_field.set_value("");
				}
				this.grid.confirm_dirty(() => {
					this.grid.target = this.mode_field.get_value();
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});

		this.item_group_field = this.page.add_field({
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
			change: this._later(() => {
				this.grid.confirm_dirty(() => {
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});

		this.item_field = this.page.add_field({
			fieldname: "item",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
			change: this._later(() => {
				this.grid.confirm_dirty(() => {
					this.grid.start = 0;
					this.grid.refresh();
				});
			}),
		});
		if (this.item_field && this.item_field.$wrapper) {
			this.item_field.$wrapper.hide();
		}

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

		this.column_groups_field = this.page.add_field({
			fieldname: "column_groups",
			label: __("Kelompok kolom"),
			fieldtype: "MultiSelectList",
			options: [
				{ label: __("Gudang & harga"), value: "stock_price", description: "" },
				{ label: __("Akun & cost center inti"), value: "core", description: "" },
				{ label: __("Akun lanjutan"), value: "advanced", description: "" },
				{ label: __("Deferred"), value: "deferred", description: "" },
			],
			change: this._later(() => {
				this.grid._render();
			}),
		});
	}

	_get_key_columns() {
		const isItem = this.mode_field ? this.mode_field.get_value() === "item" : false;
		const docType = isItem ? "Item" : "Item Group";
		return [
			{
				id: "name",
				name: isItem ? __("Item") : __("Item Group"),
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
					const link = `<a href="/app/${frappe.router.slug(docType)}/${encodeURIComponent(value)}" class="ellipsis font-weight-bold" title="${frappe.utils.escape_html(value)}">${frappe.utils.escape_html(label)}</a>`;
					const code = label !== value ? `<div class="bac-sub ellipsis">${frappe.utils.escape_html(value)}</div>` : "";
					// badge sits on the name line; centred against the two-line block it dropped below the cell
					return `<div style="min-width: 0;"><div style="display: flex; align-items: center; min-width: 0;">${link}${newBadge}</div>${code}</div>`;
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
			target: () => (this.mode_field ? this.mode_field.get_value() : "item_group"),
			key_columns: () => this._get_key_columns(),
			get_rows: {
				method: "account_bulk_config.api.item_defaults.get_rows",
				args: () => {
					const mode = this.mode_field ? this.mode_field.get_value() : "item_group";
					return {
						target: mode,
						item_group: this.item_group_field ? this.item_group_field.get_value() : null,
						item: mode === "item" && this.item_field ? this.item_field.get_value() : null,
						parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
						company: this.company_field ? this.company_field.get_value() : null,
					};
				},
			},
			get_column_groups: () => {
				const val = this.column_groups_field ? this.column_groups_field.get_value() : null;
				// no group picked = show every group, so no column is silently hidden
				return val && (Array.isArray(val) ? val.length : val) ? val : this.column_groups_field.df.options.map((o) => o.value);
			},
			get_export_filters: () => {
				const mode = this.mode_field ? this.mode_field.get_value() : "item_group";
				return {
					item_group: this.item_group_field ? this.item_group_field.get_value() : null,
					item: mode === "item" && this.item_field ? this.item_field.get_value() : null,
					parent_company: this.parent_company_field ? this.parent_company_field.get_value() : null,
					company: this.company_field ? this.company_field.get_value() : null,
				};
			},
		});
	}
}
