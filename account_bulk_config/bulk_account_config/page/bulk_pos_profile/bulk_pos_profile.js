// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

{% include "account_bulk_config/public/js/bulk_grid.js" %}

frappe.pages["bulk-pos-profile"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk POS Profile"),
		single_column: true,
	});
	wrapper.bulk_pos_profile = new BulkPOSProfilePage(page);
};

frappe.pages["bulk-pos-profile"].on_page_show = function (wrapper) {
	if (wrapper.bulk_pos_profile && wrapper.bulk_pos_profile.grid && wrapper.bulk_pos_profile.grid.state) {
		wrapper.bulk_pos_profile.grid.refresh();
	}
};

class BulkPOSProfilePage {
	constructor(page) {
		this.page = page;
		this._setup_filters();
		this._setup_grid();
		this.page.add_menu_item(__("Isi semua baris terfilter…"), () => this.fill_dialog());
		this.grid.refresh();
	}

	_later(fn) {
		return () => setTimeout(fn, 0);
	}

	_filters() {
		return {
			pos_profile: this.pos_profile_field.get_value() || null,
			parent_company: this.parent_company_field.get_value() || null,
			company: this.company_field.get_value() || null,
			include_disabled: this.include_disabled_field.get_value() ? 1 : 0,
		};
	}

	_setup_filters() {
		const reload = this._later(() => {
			this.grid.confirm_dirty(() => {
				this.grid.start = 0;
				this.grid.refresh();
			});
		});
		this.pos_profile_field = this.page.add_field({
			fieldname: "pos_profile",
			label: __("POS Profile"),
			fieldtype: "Link",
			options: "POS Profile",
			change: reload,
		});
		this.parent_company_field = this.page.add_field({
			fieldname: "parent_company",
			label: __("Parent Company"),
			fieldtype: "Link",
			options: "Company",
			change: reload,
		});
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			change: reload,
		});
		this.include_disabled_field = this.page.add_field({
			fieldname: "include_disabled",
			label: __("Termasuk nonaktif"),
			fieldtype: "Check",
			change: reload,
		});
	}

	_get_key_columns() {
		const esc = frappe.utils.escape_html;
		return [
			{
				id: "name",
				name: __("POS Profile"),
				sticky: true,
				editable: false,
				sortable: false,
				dropdown: false,
				focusable: false,
				width: 240,
				format: (value, row, column, data) => {
					const r = data || row;
					const off = r && r.disabled
						? `<span class="badge badge-secondary ml-1" style="font-size: 10px;">${__("Nonaktif")}</span>`
						: "";
					return `<div style="display: flex; align-items: center;"><a href="/app/pos-profile/${encodeURIComponent(value)}" class="ellipsis font-weight-bold" title="${esc(value)}">${esc(value)}</a>${off}</div>`;
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
				format: (value) =>
					`<a href="/app/company/${encodeURIComponent(value)}" class="ellipsis" title="${esc(value)}">${esc(value)}</a>`,
			},
		];
	}

	_setup_grid() {
		this.grid = new BulkGrid({
			page: this.page,
			target: "pos_profile",
			key_columns: () => this._get_key_columns(),
			get_rows: {
				method: "account_bulk_config.api.pos_profile.get_rows",
				args: () => this._filters(),
			},
			get_column_groups: () => ["core"],
			get_export_filters: () => this._filters(),
		});
	}

	fill_dialog() {
		// Copies one profile's values into every filtered row as pending (yellow) edits; nothing is saved yet
		const meta = this.grid.field_meta.pos_profile || [];
		const d = new frappe.ui.Dialog({
			title: __("Isi semua baris terfilter"),
			fields: [
				{
					fieldname: "source_profile",
					label: __("Ambil nilai dari POS Profile"),
					fieldtype: "Link",
					options: "POS Profile",
					reqd: 1,
				},
				{ fieldtype: "Section Break", label: __("Kolom") },
				{
					fieldname: "fields",
					fieldtype: "MultiCheck",
					options: meta.map((f) => ({ label: __(f.label), value: f.fieldname, checked: true })),
					columns: 2,
					select_all: true,
					sort_options: false,
				},
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${__("Akun/cost center/warehouse dipetakan ke company tiap baris lewat singkatan company (mis. \"- OUTLET\" menjadi \"- LBSM\"). Perubahan masuk ke tabel dulu; klik Simpan untuk menyimpan.")}</p>`,
				},
			],
			primary_action_label: __("Isi"),
			primary_action: (values) => {
				const fields = d.fields_dict.fields.get_checked_options();
				if (!fields.length) {
					frappe.msgprint(__("Pilih minimal satu kolom"));
					return;
				}
				frappe.call({
					method: "account_bulk_config.api.pos_profile.build_fill_changes",
					args: Object.assign({ source_profile: values.source_profile, fields }, this._filters()),
					freeze: true,
					callback: (r) => {
						d.hide();
						const out = r.message || { changes: [], not_found: [] };
						out.changes.forEach((c) => this.grid.dirty.set(`${c.name}|${c.company}|${c.field}`, c));
						this.grid._update_save_button();
						this.grid.refresh();
						const esc = frappe.utils.escape_html;
						const html = [
							`<p>${__("Perubahan dimuat ke tabel")}: <b>${out.changes.length}</b> · ${__("Tidak ditemukan")}: <b>${out.not_found.length}</b></p>`,
						];
						if (out.not_found.length) {
							html.push(
								`<ul class="bac-import-errors">${out.not_found
									.map((n) => `<li>${esc(n.name)} · ${esc(n.field)}: ${esc(n.value || "")}</li>`)
									.join("")}</ul>`
							);
						}
						frappe.msgprint({
							title: __("Isi semua baris"),
							indicator: out.not_found.length ? "orange" : "green",
							message: html.join(""),
						});
					},
				});
			},
		});
		d.show();
	}
}
