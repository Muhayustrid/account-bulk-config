// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

// "Koreksi Akun": swap a wrong account / cost center on a submitted voucher and repost its ledger
["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Purchase Receipt"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (frm.doc.docstatus !== 1 || !frappe.model.can_create("Repost Accounting Ledger")) return;
			frm.add_custom_button(__("Koreksi Akun"), () => bac_voucher_account_fix(frm), __("Actions"));
		},
	});
});

function bac_voucher_account_fix(frm) {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const method = (name) => `account_bulk_config.api.voucher_fix.${name}`;
	let values = [];
	let previewed = false;
	let d = null;

	d = new frappe.ui.Dialog({
		title: __("Koreksi Akun {0}", [frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "link_doctype",
				label: __("Jenis"),
				fieldtype: "Select",
				options: [
					{ label: __("Account"), value: "Account" },
					{ label: __("Cost Center"), value: "Cost Center" },
				],
				default: "Account",
				change: () => loadValues(),
			},
			{
				fieldname: "old",
				label: __("Nilai yang keliru"),
				fieldtype: "Select",
				reqd: 1,
				change: () => {
					showUsage();
					reset();
				},
			},
			{ fieldname: "usage", fieldtype: "HTML" },
			{
				fieldname: "new",
				label: __("Ganti dengan"),
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				get_query: () => ({ filters: { company: frm.doc.company, is_group: 0 } }),
				change: () => reset(),
			},
			{ fieldname: "preview_html", fieldtype: "HTML" },
		],
		primary_action_label: __("Preview"),
		primary_action: () => (previewed ? run() : doPreview()),
	});

	const reset = () => {
		if (!previewed) return;
		previewed = false;
		d.set_primary_action(__("Preview"), () => doPreview());
		d.fields_dict.preview_html.$wrapper.empty();
	};

	const showUsage = () => {
		const v = values.find((x) => x.value === d.get_value("old"));
		d.fields_dict.usage.$wrapper.html(
			v ? `<p class="text-muted small">${__("Dipakai di")}: ${v.used_in.map(esc).join(", ")}</p>` : ""
		);
	};

	const loadValues = () => {
		// the Select fires change while the dialog is still being built, before its default is set
		const link_doctype = d && d.get_value("link_doctype");
		if (!link_doctype) return;
		d.set_df_property("new", "options", link_doctype);
		d.set_value("new", null);
		reset();
		frappe
			.xcall(method("get_values"), { voucher_type: frm.doctype, voucher_no: frm.doc.name, link_doctype }, "GET")
			.then((out) => {
				values = out.values || [];
				d.set_df_property("old", "options", ["", ...values.map((v) => v.value)]);
				d.set_value("old", values.length === 1 ? values[0].value : "");
				d.fields_dict.preview_html.$wrapper.html(
					out.blocked ? `<div class="text-danger">${esc(out.blocked)}</div>` : ""
				);
			});
	};

	const doPreview = () => {
		const v = d.get_values();
		if (!v) return;
		frappe
			.xcall(
				method("preview"),
				{ voucher_type: frm.doctype, voucher_no: frm.doc.name, old: v.old, new: v.new, link_doctype: v.link_doctype },
				"GET"
			)
			.then((out) => {
				const html = [];
				if (out.rows.length) {
					html.push(
						`<p>${__("Diganti dari")} <span class="text-danger">${esc(v.old)}</span> ${__("ke")} <span class="text-success">${esc(v.new)}</span>:</p><ul>${out.rows.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
					);
				}
				if (out.warning) html.push(`<div class="text-warning">${esc(out.warning)}</div>`);
				if (out.error) html.push(`<div class="text-danger">${esc(out.error)}</div>`);
				d.fields_dict.preview_html.$wrapper.html(html.join(""));
				if (!out.error) {
					previewed = true;
					d.set_primary_action(__("Terapkan & Repost"), () => run());
				}
			});
	};

	const run = () => {
		const v = d.get_values();
		if (!v) return;
		frappe.confirm(__("Ganti {0} ke {1} di dokumen ini dan bentuk ulang jurnalnya?", [esc(v.old), esc(v.new)]), () => {
			frappe
				.xcall(
					method("apply"),
					{ voucher_type: frm.doctype, voucher_no: frm.doc.name, old: v.old, new: v.new, link_doctype: v.link_doctype },
					"POST",
					{ freeze: true, freeze_message: __("Mengoreksi dokumen…") }
				)
				.then((out) => {
					d.hide();
					const repost = (out.reposts || [])[0];
					frappe.msgprint({
						title: __("Koreksi Akun"),
						indicator: "green",
						message: repost
							? __("Dokumen dikoreksi. Jurnal dibentuk ulang lewat {0}; muat ulang halaman setelah repost selesai.", [
									`<a href="/app/repost-accounting-ledger/${encodeURIComponent(repost.name)}">${esc(repost.name)}</a>`,
							  ])
							: __("Dokumen dikoreksi."),
					});
					frm.reload_doc();
				});
		});
	};

	d.show();
	loadValues();
}
