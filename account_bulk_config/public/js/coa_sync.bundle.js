// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

// Copy a parent company's chart of accounts to its child companies (Chart of Accounts menu and
// Bulk Company Accounts menu), plus the notice for accounts copied in the background after save.

frappe.provide("account_bulk_config");

const METHOD = "account_bulk_config.api.coa_sync";
const EVENT = "bulk_account_config_coa_done";
const esc = (s) => frappe.utils.escape_html(String(s == null ? "" : s));

function list(items, limit = 50) {
	if (!items.length) return "";
	const more =
		items.length > limit ? `<li class="text-muted">${__("… dan {0} lagi", [items.length - limit])}</li>` : "";
	return `<ul class="bac-import-errors">${items
		.slice(0, limit)
		.map((i) => `<li>${i}</li>`)
		.join("")}${more}</ul>`;
}

function preview_html(plans) {
	if (!plans.length) return `<p class="text-muted">${__("Tidak ada anak perusahaan.")}</p>`;
	return plans
		.map((p) => {
			const create = p.create.map(
				(r) => `${esc(r.label)} <span class="text-muted">→ ${esc(r.parent_label || __("akar"))}</span>`,
			);
			const update = p.update.map((r) => `${esc(r.account)}: ${r.changes.map(esc).join(", ")}`);
			const remove = (p.delete || []).map((r) => esc(r.label));
			const issues = p.issues.map(esc);
			const nothing =
				!create.length && !update.length && !remove.length && !issues.length
					? `<div class="text-muted">${__("Sudah sama dengan parent.")}</div>`
					: "";
			return `<div class="mb-3"><b>${esc(p.company)}</b> · ${__("Dibuat")}: <b>${create.length}</b> · ${__("Diupdate")}: <b>${update.length}</b> · ${__("Dihapus")}: <b>${remove.length}</b> · ${__("Bermasalah")}: <b>${issues.length}</b>
				${create.length ? `<div class="mt-1">${__("Akun baru")}:</div>${list(create)}` : ""}
				${update.length ? `<div class="mt-1">${__("Akun diupdate")}:</div>${list(update)}` : ""}
				${remove.length ? `<div class="mt-1 text-danger">${__("Akun dihapus")}:</div>${list(remove)}` : ""}
				${issues.length ? `<div class="mt-1 text-danger">${__("Dilewati")}:</div>${list(issues)}` : ""}${nothing}</div>`;
		})
		.join("");
}

function show_results(results, title, error) {
	const bad = error || results.some((r) => r.error || r.issues.length);
	frappe.msgprint({
		title: title || __("Hasil Salin COA"),
		indicator: error ? "red" : bad ? "orange" : "green",
		message:
			(error ? `<div class="text-danger mb-3">${__("Salin COA gagal")}: ${esc(error)}</div>` : "") +
			results
				.map(
					(
						r,
					) => `<div class="mb-3"><b>${esc(r.company)}</b> · ${__("Dibuat")}: <b>${r.created}</b> · ${__("Diupdate")}: <b>${r.updated}</b> · ${__("Dihapus")}: <b>${r.deleted || 0}</b>
				${r.error ? `<div class="text-danger">${__("Gagal, tidak ada yang disimpan")}: ${esc(r.error)}</div>` : ""}
				${r.issues.length ? `<div class="text-danger">${__("Dilewati")}:</div>${list(r.issues.map(esc))}` : ""}</div>`,
				)
				.join(""),
	});
}

account_bulk_config.coa_sync_dialog = function (parent_company) {
	let previewed = null;
	const d = new frappe.ui.Dialog({
		title: __("Salin COA ke Anak Perusahaan"),
		size: "large",
		fields: [
			{
				fieldname: "parent_company",
				label: __("Company Induk"),
				fieldtype: "Link",
				options: "Company",
				reqd: 1,
				get_query: () => ({ filters: { is_group: 1 } }),
				change: () => load_children(),
			},
			{
				fieldname: "update_existing",
				label: __(
					"Samakan juga induk akun, nomor akun, Account Type, Freeze dan Balance Must Be di akun yang sudah ada",
				),
				fieldtype: "Check",
				default: 1,
				change: () => reset(),
			},
			{
				fieldname: "delete_missing",
				label: __("Hapus akun di anak yang tidak ada di induk (akun yang sudah ada transaksinya tetap)"),
				fieldtype: "Check",
				default: 0,
				change: () => reset(),
			},
			{
				fieldname: "companies",
				label: __("Anak Perusahaan"),
				fieldtype: "MultiCheck",
				options: [],
				columns: 2,
				select_all: 1,
				on_change: () => reset(),
			},
			{
				fieldname: "help",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Akun dicocokkan berdasarkan nama (dan nomor akun bila ada). Akun yang belum ada dibuat di bawah induk yang sama, induknya ikut dibuat bila perlu. Akun yang hanya ada di anak tidak disentuh, kecuali opsi hapus dicentang.",
				)}</p>`,
			},
			{ fieldname: "preview", fieldtype: "HTML" },
		],
		primary_action_label: __("Preview"),
		primary_action: () => (previewed ? run() : do_preview()),
	});

	const reset = () => {
		previewed = null;
		d.set_primary_action(__("Preview"), () => do_preview());
		d.fields_dict.preview.$wrapper.empty();
	};

	// a copy: the control keeps mutating its own array as boxes are ticked
	const args = () => ({
		parent_company: d.get_value("parent_company"),
		companies: [...d.fields_dict.companies.get_checked_options()],
		update_existing: d.get_value("update_existing") ? 1 : 0,
		delete_missing: d.get_value("delete_missing") ? 1 : 0,
	});

	function load_children() {
		reset();
		const company = d.get_value("parent_company");
		const field = d.fields_dict.companies;
		if (!company) {
			field.df.options = [];
			field.refresh();
			return;
		}
		frappe.xcall(`${METHOD}.get_children`, { parent_company: company }).then((children) => {
			field.df.options = children.map((c) => ({ label: c, value: c, checked: 1 }));
			field.refresh();
		});
	}

	function do_preview() {
		const a = args();
		if (!a.parent_company) return;
		if (!a.companies.length) {
			frappe.msgprint(__("Pilih minimal satu anak perusahaan"));
			return;
		}
		frappe
			// POST: the list of children can be too long for a GET URL
			.xcall(`${METHOD}.preview`, a, "POST", {
				freeze: true,
				freeze_message: __("Membandingkan COA…"),
			})
			.then((plans) => {
				const $preview = d.fields_dict.preview.$wrapper.html(preview_html(plans));
				// the preview sits below the list of children, out of sight in a long dialog
				$preview.get(0).scrollIntoView({ behavior: "smooth", block: "start" });
				const total = plans.reduce(
					(n, p) => n + p.create.length + p.update.length + (p.delete || []).length,
					0,
				);
				if (!total) {
					const issues = plans.reduce((n, p) => n + p.issues.length, 0);
					frappe.show_alert({
						message: issues
							? __("Tidak ada yang bisa disalin; {0} akun bermasalah, lihat preview", [issues])
							: __("COA anak perusahaan sudah sama dengan induk"),
						indicator: issues ? "orange" : "green",
					});
					return;
				}
				previewed = a;
				d.set_primary_action(__("Salin ({0})", [total]), () => run());
			});
	}

	function run() {
		const a = previewed;
		const question = a.delete_missing
			? __("Buat/update/hapus akun di anak perusahaan sesuai COA {0}?", [a.parent_company])
			: __("Buat/update akun di anak perusahaan sesuai COA {0}?", [a.parent_company]);
		frappe.confirm(question, () => {
			// listen before the call: a quick job can finish before the response arrives
			let job_id = null;
			const early = [];
			const done = (data) => {
				frappe.realtime.off(EVENT, handler);
				show_results(data.results || [], null, data.error);
			};
			const handler = (data) => {
				if (!data || data.account) return;
				if (!job_id) early.push(data);
				else if (data.job_id === job_id) done(data);
			};
			frappe.realtime.on(EVENT, handler);
			frappe
				.xcall(`${METHOD}.apply`, a, "POST", { freeze: true, freeze_message: __("Menyalin COA…") })
				.then((out) => {
					d.hide();
					if (out.results) {
						frappe.realtime.off(EVENT, handler);
						show_results(out.results);
						return;
					}
					frappe.show_alert({
						message: __("{0} akun diproses di background", [out.total]),
						indicator: "blue",
					});
					job_id = out.job_id;
					const finished = early.find((data) => data.job_id === job_id);
					if (finished) done(finished);
				})
				.catch(() => frappe.realtime.off(EVENT, handler));
		});
	}

	d.show();
	if (parent_company) d.set_value("parent_company", parent_company);
	return d;
};

// account saved in a parent company: its copies were made by a background job
$(document).on("app_ready", () => {
	frappe.realtime.on(EVENT, (data) => {
		if (!data || !data.account) return;
		const results = data.results || [];
		if (data.error || results.some((r) => r.error || r.issues.length)) {
			show_results(results, __("Salin {0} ke anak perusahaan", [data.account]), data.error);
			return;
		}
		const created = results.reduce((n, r) => n + r.created + r.updated, 0);
		if (created) {
			frappe.show_alert({
				message: __("{0} disalin ke {1} anak perusahaan", [esc(data.account), results.length]),
				indicator: "green",
			});
		}
		if (window.cur_tree && frappe.get_route()[1] === "Account")
			cur_tree.reload_node(cur_tree.get_selected_node());
	});
});
