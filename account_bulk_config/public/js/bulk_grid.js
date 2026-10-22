// Copyright (c) 2026, Rotiri Project and contributors
// For license information, please see license.txt

(function (root, factory) {
	if (typeof module === "object" && module.exports) {
		module.exports = factory();
	} else {
		root.BulkGrid = factory();
	}
})(typeof window !== "undefined" ? window : globalThis, function () {
	class BulkGrid {
		constructor(opts) {
			this.page = opts.page;
			this.target = opts.target; // String or function returning target ("company", "item", "item_group", "mode_of_payment")
			this.key_columns = opts.key_columns || [];
			this.get_rows_config = opts.get_rows || {};
			this.get_column_groups = opts.get_column_groups || (() => ["core"]);
			this.get_export_filters = opts.get_export_filters || (() => ({}));
			this.on_render = opts.on_render;

			this.state = null;
			this.start = 0;
			this.page_length = 20;
			this.datatable = null;
			this.field_meta = {};
			this.dirty = new Map();
			this.last_errors = new Map();

			this._setup_actions();
			this._setup_beforeunload();

			this.$root = $('<div class="bac-page">').appendTo(this.page.main);
			this.$root.html(`<p class="text-muted">${__("Loading...")}</p>`);
		}

		getTarget() {
			return typeof this.target === "function" ? this.target() : this.target;
		}

		load_field_meta() {
			const target = this.getTarget();
			if (this.field_meta[target]) {
				return Promise.resolve(this.field_meta[target]);
			}
			return new Promise((resolve, reject) => {
				frappe.call({
					method: "account_bulk_config.api.fields.get_field_meta",
					args: { target: target },
					callback: (r) => {
						this.field_meta[target] = r.message || [];
						resolve(this.field_meta[target]);
					},
					error: reject,
				});
			});
		}

		_setup_actions() {
			this.$btn_save = this.page.set_primary_action(
				__("Simpan"),
				() => this.save(),
				null,
				__("Simpan perubahan")
			);
			this.$btn_save.prop("disabled", true).removeClass("btn-primary").addClass("btn-default");

			this.$btn_cancel = this.page.add_button(__("Batalkan perubahan"), () => {
				this.cancel_changes();
			});
			this.$btn_cancel.hide();

			this.page.add_button(__("Refresh"), () => {
				this.confirm_dirty(() => this.refresh());
			});

			this.page.add_menu_item(__("Export Excel"), () => this.export_excel(false));
			this.page.add_menu_item(__("Download Template"), () => this.export_excel(true));
			this.page.add_menu_item(__("Import Excel"), () => this.import_dialog());
			this.page.add_menu_item(__("Copy from Outlet"), () => this.copy_from_outlet_dialog());
			this.page.add_menu_item(__("Terapkan ke anak…"), () => this.apply_to_children_dialog());
		}

		_setup_beforeunload() {
			window.addEventListener("beforeunload", (e) => {
				if (this.dirty && this.dirty.size > 0) {
					e.preventDefault();
					e.returnValue = "";
					return "";
				}
			});
		}

		_update_save_button() {
			const count = this.dirty.size;
			if (this.$btn_save) {
				if (count > 0) {
					this.$btn_save
						.text(__("Simpan ({0})", [count]))
						.prop("disabled", false)
						.addClass("btn-primary")
						.removeClass("btn-default");
				} else {
					this.$btn_save
						.text(__("Simpan"))
						.prop("disabled", true)
						.removeClass("btn-primary")
						.addClass("btn-default");
				}
			}
			if (this.$btn_cancel) {
				this.$btn_cancel.toggle(count > 0);
			}
		}

		confirm_dirty(on_proceed) {
			if (this.dirty.size > 0) {
				frappe.confirm(
					__("Ada {0} perubahan yang belum disimpan. Yakin ingin berpindah?", [this.dirty.size]),
					() => {
						this.dirty.clear();
						this._update_save_button();
						on_proceed();
					}
				);
			} else {
				on_proceed();
			}
		}

		cancel_changes() {
			if (this.dirty.size === 0) return;
			frappe.confirm(
				__("Batalkan semua perubahan yang belum disimpan?"),
				() => {
					this.dirty.clear();
					this._update_save_button();
					this.refresh();
				}
			);
		}

		refresh() {
			if (!this.$root) return Promise.resolve();
			return Promise.all([
				this.load_field_meta(),
				new Promise((resolve) => {
					const args = typeof this.get_rows_config.args === "function"
						? this.get_rows_config.args()
						: Object.assign({}, this.get_rows_config.args || {});
					args.start = this.start;
					args.page_length = this.page_length;

					frappe.call({
						method: this.get_rows_config.method,
						args: args,
						freeze: true,
						callback: (r) => {
							if (r.message) {
								this.state = r.message;
								this._render();
							}
							resolve();
						},
						error: (r) => {
							this._render_error(r);
							resolve();
						},
					});
				}),
			]);
		}

		_render_error(r) {
			if (this.datatable) {
				this.datatable.destroy();
				this.datatable = null;
			}
			let msg = __("Gagal memuat data");
			const exc = r && r.exc ? String(r.exc).trim().split("\n").filter(Boolean) : [];
			if (exc.length) msg = exc[exc.length - 1];
			this.$root.html(
				`<div class="frappe-card"><p class="text-muted">${frappe.utils.escape_html(msg)}</p></div>`
			);
		}

		_render() {
			const rows = (this.state && this.state.rows) || [];
			const total = (this.state && this.state.total) || 0;
			const target = this.getTarget();
			const meta = this.field_meta[target] || [];

			// Snapshot original values and overlay local dirty changes
			rows.forEach((r) => {
				if (!r._orig) {
					r._orig = Object.assign({}, r);
				}
				const rowCompany = r.company || r.name;
				for (const [key, change] of this.dirty.entries()) {
					const parts = key.split("|");
					if (parts[0] === r.name && parts[1] === rowCompany) {
						r[parts[2]] = change.new;
					}
				}
			});

			if (!rows.length) {
				if (this.datatable) {
					this.datatable.destroy();
					this.datatable = null;
				}
				this.$root.html(
					`<div class="frappe-card"><p class="text-muted">${__("Tidak ada data")}</p></div>`
				);
				return;
			}

			if (this.datatable) {
				this.datatable.destroy();
				this.datatable = null;
			}

			this.$root.html([
				`<div class="frappe-card"><div class="bac-datatable-wrapper"></div></div>`,
				this._pager(total),
			].join(""));
			this._bind_pager();

			const $wrapper = this.$root.find(".bac-datatable-wrapper");
			const columns = this._build_columns(meta);
			this._current_columns = columns;

			this.datatable = new frappe.DataTable($wrapper[0], {
				columns: columns,
				data: rows.map((r) => this._row_object(r, columns)),
				serialNoColumn: false,
				checkboxColumn: false,
				inlineFilters: false,
				headerDropdown: [],
				// "fluid" forces overflow-x hidden and squeezes columns; "fixed" allows horizontal scroll
				layout: "fixed",
				cellHeight: 35,
				language: frappe.boot.lang,
				translations: frappe.utils.datatable.get_translations(),
				direction: frappe.utils.is_rtl() ? "rtl" : "ltr",
				getEditor: this._get_editor.bind(this),
			});

			if (this.on_render) this.on_render();
		}

		_get_active_groups() {
			const val = typeof this.get_column_groups === "function" ? this.get_column_groups() : ["core"];
			if (!val || (Array.isArray(val) && !val.length)) return ["core"];
			if (typeof val === "string") return val.split(",").map((s) => s.trim()).filter(Boolean);
			return val;
		}

		_build_columns(meta) {
			const activeGroups = this._get_active_groups();
			const keyCols = typeof this.key_columns === "function" ? this.key_columns() : this.key_columns;
			const cols = keyCols.map((k) => Object.assign({ sticky: true }, k));
			const activeFields = meta.filter((f) => activeGroups.includes(f.group));

			activeFields.forEach((fdef) => {
				cols.push({
					id: fdef.fieldname,
					name: __(fdef.label),
					width: 240,
					editable: !fdef.read_only,
					focusable: !fdef.read_only,
					sortable: false,
					dropdown: false,
					docfield: {
						fieldname: fdef.fieldname,
						fieldtype: fdef.read_only ? "Data" : "Link",
						options: fdef.link,
						label: __(fdef.label),
						read_only: fdef.read_only ? 1 : 0,
					},
					fdef: fdef,
					format: (value, row, column, data) => {
						const r = data || row;
						const isDirty = this._is_dirty(r, fdef.fieldname);
						const valStr = value != null ? frappe.utils.escape_html(String(value)) : "";
						if (isDirty) {
							const err = r && this.last_errors.get(`${r.name}|${r.company || r.name}`);
							if (err) {
								return `<div class="bac-dirty bac-error" title="${frappe.utils.escape_html(err)}" style="width: 100%; height: 100%; min-height: 20px; padding: 0 4px; display: flex; align-items: center;">${valStr || "&nbsp;"}</div>`;
							}
							return `<div class="bac-dirty" style="background: var(--bg-yellow); width: 100%; height: 100%; min-height: 20px; padding: 0 4px; display: flex; align-items: center;">${valStr || "&nbsp;"}</div>`;
						}
						return valStr;
					},
				});
			});
			return cols;
		}

		_row_object(r, columns) {
			const obj = Object.assign({}, r);
			columns.forEach((c) => {
				if (obj[c.id] === undefined) obj[c.id] = null;
			});
			return obj;
		}

		_row_values(r) {
			return (this._current_columns || []).map((col) => r[col.id]);
		}

		_is_dirty(r, fieldname) {
			if (!r) return false;
			const name = r.name;
			const company = r.company || r.name;
			const key = `${name}|${company}|${fieldname}`;
			return this.dirty.has(key);
		}

		_get_editor(colIndex, rowIndex, value, parent) {
			const col = this.datatable.getColumn(colIndex);
			if (!col || !col.editable || !col.docfield) return false;

			const rowData = (this.state && this.state.rows && this.state.rows[rowIndex]) || {};
			const company = rowData.company || rowData.name;
			const fdef = col.fdef || {};

			const control = frappe.ui.form.make_control({
				df: Object.assign({}, col.docfield),
				parent: parent,
				render_input: true,
			});
			if (!control) return false;

			const COMPANY_SCOPED = ["Account", "Cost Center", "Warehouse"];
			if (COMPANY_SCOPED.includes(fdef.link)) {
				const queryFilters = Object.assign({}, fdef.filters || {}, {
					company: company,
					is_group: 0,
				});
				control.get_query = () => ({ filters: queryFilters });
				if (control.df) control.df.get_query = () => ({ filters: queryFilters });
			}

			control.set_value(value);
			control.toggle_label(false);
			control.toggle_description(false);
			if (control.df) {
				control.df.change = () => control.set_focus && control.set_focus();
			}

			return {
				initValue: (val) => {
					const res = control.set_value(val);
					if (control.set_focus) control.set_focus();
					return res;
				},
				setValue: (val) => {
					control.set_value(val);
					const current = (this.state && this.state.rows && this.state.rows[rowIndex]) || rowData;
					const rowName = current.name;
					const rowCompany = current.company || current.name;
					const fieldname = col.docfield.fieldname;
					const dirtyKey = `${rowName}|${rowCompany}|${fieldname}`;

					const cleanVal = val === "" || val === undefined ? null : val;
					const origVal =
						current._orig && current._orig[fieldname] !== undefined
							? current._orig[fieldname]
							: (current[fieldname] ?? null);

					if (cleanVal === origVal) {
						this.dirty.delete(dirtyKey);
					} else {
						this.dirty.set(dirtyKey, {
							name: rowName,
							company: rowCompany,
							field: fieldname,
							old: origVal,
							new: cleanVal,
							company_is_group: current.company_is_group || current.is_group || 0,
							is_group: current.is_group || 0,
						});
					}

					current[fieldname] = cleanVal;
					if (this.datatable && this.datatable.datamanager && this.datatable.datamanager.data) {
						const dmRow = this.datatable.datamanager.data[rowIndex];
						if (dmRow) dmRow[fieldname] = cleanVal;
					}
					this._update_save_button();
					this.datatable.refreshRow(this._row_values(current), rowIndex);
					return Promise.resolve(cleanVal);
				},
				getValue: () => {
					let val = control.get_value();
					if (val === "" || val === undefined) val = null;
					return Promise.resolve(val);
				},
			};
		}

		_pager(total) {
			const from = total > 0 ? this.start + 1 : 0;
			const to = Math.min(this.start + this.page_length, total);
			const sizes = [20, 100, 500];
			const sizeBtns = sizes
				.map(
					(n) =>
						`<button class="btn btn-xs btn-default${n === this.page_length ? " btn-primary" : ""}" data-bac-size="${n}">${n}</button>`
				)
				.join("");
			return `<div class="bac-pager">
				<span class="bac-pager-sizes">${sizeBtns}</span>
				<span class="bac-pager-nav">
					<button class="btn btn-xs btn-default" data-bac-prev ${this.start <= 0 ? "disabled" : ""}>${__("Previous")}</button>
					<button class="btn btn-xs btn-default" data-bac-next ${to >= total ? "disabled" : ""}>${__("Next")}</button>
				</span>
				<span class="bac-sub text-muted">${from}–${to} ${__("of {0}", [total])}</span>
			</div>`;
		}

		_bind_pager() {
			this.$root
				.off("click", "[data-bac-size]")
				.on("click", "[data-bac-size]", (e) => {
					const newLen = Number($(e.currentTarget).data("bac-size"));
					this.confirm_dirty(() => {
						this.page_length = newLen;
						this.start = 0;
						this.refresh();
					});
				})
				.off("click", "[data-bac-prev]")
				.on("click", "[data-bac-prev]", () => {
					this.confirm_dirty(() => {
						this.start = Math.max(0, this.start - this.page_length);
						this.refresh();
					});
				})
				.off("click", "[data-bac-next]")
				.on("click", "[data-bac-next]", () => {
					this.confirm_dirty(() => {
						this.start = this.start + this.page_length;
						this.refresh();
					});
				});
		}

		save() {
			if (this.dirty.size === 0) return;
			const changes = Array.from(this.dirty.values());
			const hasGroupChange = changes.some((c) => c.company_is_group || c.is_group);

			if (hasGroupChange) {
				frappe.call({
					method: "account_bulk_config.api.propagation.preview_propagation",
					args: {
						target: this.getTarget(),
						changes: changes,
						depth: "children",
					},
					freeze: true,
					callback: (r) => {
						const previewRows = r.message || [];
						if (!previewRows.length) {
							this._do_save(changes);
							return;
						}
						this._show_propagation_dialog(changes, previewRows, "children");
					},
				});
			} else {
				this._do_save(changes);
			}
		}

		_show_propagation_dialog(parentChanges, previewRows, currentDepth, targetOverride) {
			const me = this;
			const dialog = new frappe.ui.Dialog({
				title: __("Terapkan ke anak company?"),
				size: "large",
				fields: [
					{
						fieldname: "depth",
						label: __("Kedalaman"),
						fieldtype: "Select",
						options: [
							{ label: __("Anak langsung"), value: "children" },
							{ label: __("Semua turunan"), value: "all" },
						],
						default: currentDepth,
						change: () => {
							const newDepth = dialog.get_value("depth");
							if (newDepth !== currentDepth) {
								frappe.call({
									method: "account_bulk_config.api.propagation.preview_propagation",
									args: {
										target: me.getTarget(),
										changes: parentChanges,
										depth: newDepth,
										targets: targetOverride || null,
									},
									freeze: true,
									callback: (r) => {
										dialog.hide();
										me._show_propagation_dialog(parentChanges, r.message || [], newDepth, targetOverride);
									},
								});
							}
						},
					},
					{
						fieldname: "summary_html",
						fieldtype: "HTML",
					},
					{
						fieldname: "shortcuts_html",
						fieldtype: "HTML",
					},
					{
						fieldname: "table_area",
						fieldtype: "HTML",
					},
				],
			});

			if (targetOverride) {
				dialog.get_field("depth").$wrapper.hide();
			}

			const counts = { changed: 0, same: 0, exception: 0, not_found: 0 };
			previewRows.forEach((it) => {
				counts[it.status] = (counts[it.status] || 0) + 1;
			});
			const uniqueChildren = new Set(previewRows.map((it) => it.company)).size;
			const uniqueFields = new Set(previewRows.map((it) => it.field)).size;

			dialog.get_field("summary_html").$wrapper.html(`
				<div class="bac-prop-summary text-muted mb-2">
					<b>${uniqueFields} field × ${uniqueChildren} anak</b>;
					<span class="text-success font-weight-bold">🟢 ${counts.changed || 0} ${__("berubah")}</span>,
					<span class="text-secondary">⚪ ${counts.same || 0} ${__("sudah sama")}</span>,
					<span class="text-warning font-weight-bold">🟠 ${counts.exception || 0} ${__("pengecualian")}</span>,
					<span class="text-danger font-weight-bold">🔴 ${counts.not_found || 0} ${__("tidak ditemukan")}</span>
				</div>
			`);

			dialog.get_field("shortcuts_html").$wrapper.html(`
				<div class="mb-2 d-flex gap-2" style="gap: 8px;">
					<button class="btn btn-xs btn-default btn-check-all">${__("Centang semua")}</button>
					<button class="btn btn-xs btn-default btn-check-induk">${__("Hanya yang mengikuti induk")}</button>
					<button class="btn btn-xs btn-default btn-uncheck-all">${__("Kosongkan")}</button>
				</div>
			`);

			const $tableWrapper = $(
				'<div class="bac-prop-table-wrapper" style="min-height: 250px; max-height: 400px; overflow-y: auto;"></div>'
			);
			dialog.get_field("table_area").$wrapper.append($tableWrapper);

			const propCols = [
				{ id: "company", name: __("Company Anak"), editable: false, width: 170 },
				{ id: "field", name: __("Field"), editable: false, width: 160 },
				{ id: "old", name: __("Nilai Lama"), editable: false, width: 150 },
				{ id: "new", name: __("Nilai Baru"), editable: false, width: 150 },
				{
					id: "status",
					name: __("Status"),
					editable: false,
					width: 120,
					format: (val) => {
						const pillColor =
							val === "changed"
								? "green"
								: val === "exception"
									? "orange"
									: val === "not_found"
										? "red"
										: "gray";
						const label =
							val === "changed"
								? __("berubah")
								: val === "exception"
									? __("pengecualian")
									: val === "not_found"
										? __("tidak ditemukan")
										: __("sudah sama");
						return `<span class="indicator-pill ${pillColor}">${label}</span>`;
					},
				},
			];

			const propData = previewRows.map((r) => ({
				company: r.company,
				field: r.field,
				old: r.old || "",
				new: r.new || "",
				status: r.status,
			}));

			// DataTable injects a <style> whose sheet is null until the modal is attached to the document
			let dt;
			dialog.$wrapper.one("shown.bs.modal", () => {
				dt = new frappe.DataTable($tableWrapper[0], {
					columns: propCols,
					data: propData,
					serialNoColumn: false,
					checkboxColumn: true,
					inlineFilters: false,
					headerDropdown: [],
					layout: "fluid",
					cellHeight: 32,
				});
				previewRows.forEach((r, idx) => {
					dt.rowmanager.checkRow(idx, !!r.checked && r.status !== "not_found");
				});
				updateActionButtons();
			});

			function getCheckedCount() {
				let cnt = 0;
				previewRows.forEach((r, idx) => {
					if (
						dt.rowmanager &&
						dt.rowmanager.checkMap &&
						dt.rowmanager.checkMap[idx] == 1 &&
						r.status !== "not_found"
					) {
						cnt++;
					}
				});
				return cnt;
			}

			function updateActionButtons() {
				const checkedCount = getCheckedCount();
				dialog.set_primary_action(
					checkedCount > 0
						? __("Simpan induk + {0} anak", [checkedCount])
						: __("Simpan"),
					() => {
						const childChanges = [];
						previewRows.forEach((r, idx) => {
							if (
								dt.rowmanager &&
								dt.rowmanager.checkMap &&
								dt.rowmanager.checkMap[idx] == 1 &&
								r.status !== "not_found"
							) {
								childChanges.push({
									name: r.name,
									company: r.company,
									field: r.field,
									old: r.old,
									new: r.new,
								});
							}
						});
						dialog.hide();
						me._do_save(parentChanges.concat(childChanges));
					}
				);
			}

			dialog.$wrapper.on("click", 'input[type="checkbox"]', () => {
				setTimeout(() => {
					// the header "select all" also ticks rows that cannot be applied
					previewRows.forEach((r, idx) => {
						if (r.status === "not_found" && dt.rowmanager.checkMap[idx] == 1) {
							dt.rowmanager.checkRow(idx, false);
						}
					});
					updateActionButtons();
				}, 10);
			});
			// discard the modal DOM instead of piling hidden dialogs on every depth switch
			dialog.$wrapper.on("hidden.bs.modal", () => dialog.$wrapper.remove());

			// shortcut buttons are visible before the table exists (created on "shown")
			dialog.$wrapper.find(".btn-check-all, .btn-check-induk, .btn-uncheck-all").on("click", (e) => {
				if (!dt) e.stopImmediatePropagation();
			});

			dialog.$wrapper.find(".btn-check-all").on("click", (e) => {
				e.preventDefault();
				previewRows.forEach((r, idx) => {
					dt.rowmanager.checkRow(idx, r.status !== "not_found");
				});
				updateActionButtons();
			});

			dialog.$wrapper.find(".btn-check-induk").on("click", (e) => {
				e.preventDefault();
				previewRows.forEach((r, idx) => {
					dt.rowmanager.checkRow(idx, r.status === "changed");
				});
				updateActionButtons();
			});

			dialog.$wrapper.find(".btn-uncheck-all").on("click", (e) => {
				e.preventDefault();
				previewRows.forEach((r, idx) => {
					dt.rowmanager.checkRow(idx, false);
				});
				updateActionButtons();
			});

			dialog.set_secondary_action_label(__("Simpan induk saja"));
			dialog.set_secondary_action(() => {
				dialog.hide();
				me._do_save(parentChanges);
			});

			dialog.show();
		}

		_do_save(changes) {
			// Save a few documents per request so the native progress bar advances
			// without depending on realtime (socket.io) events.
			const CHUNK_DOCS = 5;
			const CHUNK_CHANGES = 200;
			if (this._saving) return;
			this._saving = true;
			const byDoc = new Map();
			// "Terapkan ke anak" sends the group row with old == new; saving it would be a pointless write
			changes
				.filter((c) => (c.old || null) !== (c.new || null))
				.forEach((c) => {
					if (!byDoc.has(c.name)) byDoc.set(c.name, []);
					byDoc.get(c.name).push(c);
				});
			const docs = Array.from(byDoc.keys());
			if (!docs.length) {
				this._saving = false;
				frappe.show_alert({ message: __("Tidak ada perubahan untuk disimpan"), indicator: "orange" });
				return;
			}
			// a document is never split across requests (its stale check is per document)
			const nextBatch = (from) => {
				let end = from;
				let size = 0;
				while (end < docs.length && end - from < CHUNK_DOCS && (end === from || size + byDoc.get(docs[end]).length <= CHUNK_CHANGES)) {
					size += byDoc.get(docs[end]).length;
					end++;
				}
				return docs.slice(from, end);
			};
			const title = __("Menyimpan perubahan");
			const results = [];
			let done = 0;

			const next = () => {
				if (done >= docs.length) {
					this._saving = false;
					frappe.hide_progress();
					this._handle_save_results(results);
					return;
				}
				const batch = nextBatch(done);
				frappe.show_progress(title, done, docs.length, __("{0} dari {1} dokumen", [done, docs.length]), true);
				frappe
					.xcall("account_bulk_config.api.batch.save_changes", {
						target: this.getTarget(),
						changes: batch.flatMap((n) => byDoc.get(n)),
					})
					.then((out) => {
						results.push(...((out && out.results) || []));
						done += batch.length;
						next();
					})
					.catch(() => {
						// remaining documents stay dirty so the user can retry
						this._saving = false;
						frappe.hide_progress();
						if (results.length) this._handle_save_results(results);
					});
			};
			next();
		}

		_handle_save_results(results) {
			const okCount = results.filter((r) => r.status === "ok").length;
			const skippedCount = results.filter((r) => r.status === "skipped").length;
			const errors = results.filter((r) => r.status !== "ok");

			this.last_errors.clear();
			results.forEach((r) => {
				const key = `${r.name}|${r.company}`;
				if (r.status === "error") {
					this.last_errors.set(key, r.message);
				} else if (r.status === "ok") {
					for (const dKey of Array.from(this.dirty.keys())) {
						if (dKey.startsWith(key + "|")) {
							this.dirty.delete(dKey);
						}
					}
				}
			});

			this._update_save_button();

			const html = [
				`<p>${__("Berhasil")}: <b>${okCount}</b> · ${__("Dilewati")}: <b>${skippedCount}</b> · ${__("Error")}: <b>${errors.length - skippedCount}</b></p>`,
			];
			if (errors.length) {
				html.push(
					`<ul class="bac-import-errors">${errors
						.map(
							(e) =>
								`<li>${frappe.utils.escape_html(e.name || "")} (${frappe.utils.escape_html(e.company || "")}): ${frappe.utils.escape_html(e.message || "")}</li>`
						)
						.join("")}</ul>`
				);
			}

			frappe.msgprint({
				title: __("Hasil Simpan"),
				indicator: errors.length ? "orange" : "green",
				message: html.join(""),
			});

			this.refresh();
		}

		export_excel(is_template) {
			// Dialog pre-filled from the page filters; the user can narrow rows and pick columns freely
			const target = this.getTarget();
			const filters = typeof this.get_export_filters === "function" ? this.get_export_filters() : {};
			const filterDefs = {
				parent_company: { label: __("Parent Company"), fieldtype: "Link", options: "Company" },
				company: { label: __("Company"), fieldtype: "Link", options: "Company" },
				search: { label: __("Cari company"), fieldtype: "Data" },
				item_group: { label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
				item: { label: __("Item"), fieldtype: "Link", options: "Item" },
				mode_of_payment: { label: __("Mode of Payment"), fieldtype: "Link", options: "Mode of Payment" },
			};
			const filterKeys = Object.keys(filters).filter(
				(k) => filterDefs[k] && (k !== "item" || target === "item")
			);
			const activeGroups = this._get_active_groups();
			const fieldOptions = (this.field_meta[target] || [])
				.filter((f) => !f.read_only)
				.map((f) => ({ label: __(f.label), value: f.fieldname, checked: activeGroups.includes(f.group) }));

			const d = new frappe.ui.Dialog({
				title: __("Export Excel"),
				size: "large",
				fields: [
					{
						fieldname: "kind",
						label: __("Isi"),
						fieldtype: "Select",
						options: [
							{ label: __("Data saat ini"), value: "0" },
							{ label: __("Template kosong"), value: "1" },
						],
						default: is_template ? "1" : "0",
					},
					...filterKeys.map((k) => Object.assign({ fieldname: k, default: filters[k] || "" }, filterDefs[k])),
					{ fieldtype: "Section Break", label: __("Kolom") },
					{
						fieldname: "fields",
						fieldtype: "MultiCheck",
						options: fieldOptions,
						columns: 2,
						select_all: true,
						sort_options: false,
					},
				],
				primary_action_label: __("Export"),
				primary_action: (values) => {
					const fields = d.fields_dict.fields.get_checked_options();
					if (!fields.length) {
						frappe.msgprint(__("Pilih minimal satu kolom"));
						return;
					}
					const params = new URLSearchParams({ target, template: values.kind, fields: fields.join(",") });
					filterKeys.forEach((k) => {
						if (values[k]) params.set(k, values[k]);
					});
					window.open(
						frappe.urllib.get_full_url(
							`/api/method/account_bulk_config.api.excel.export_sheet?${params.toString()}`
						)
					);
					d.hide();
				},
			});
			d.show();
		}

		import_dialog() {
			const d = new frappe.ui.Dialog({
				title: __("Import Excel"),
				fields: [
					{
						fieldname: "file",
						label: __("File Excel (.xlsx)"),
						fieldtype: "Attach",
						options: { restrictions: { allowed_file_types: [".xlsx"], max_file_size: 5 * 1024 * 1024 } },
					},
				],
				primary_action_label: __("Import"),
				primary_action: (values) => {
					if (!values.file) {
						frappe.msgprint(__("Pilih file terlebih dahulu"));
						return;
					}
					frappe.call({
						method: "account_bulk_config.api.excel.import_sheet",
						args: {
							target: this.getTarget(),
							file_url: values.file,
						},
						freeze: true,
						callback: (r) => {
							d.hide();
							const out = r.message || { changes: [], errors: [] };
							const changes = out.changes || [];
							const errors = out.errors || [];

							changes.forEach((c) => {
								const key = `${c.name}|${c.company}|${c.field}`;
								this.dirty.set(key, c);
								if (this.state && this.state.rows) {
									const row = this.state.rows.find(
										(rowItem) =>
											rowItem.name === c.name &&
											(rowItem.company || rowItem.name) === c.company
									);
									if (row) {
										row[c.field] = c.new;
									}
								}
							});

							this._update_save_button();
							this._render();

							const html = [
								`<p>${__("Perubahan dimuat ke tabel")}: <b>${changes.length}</b> · ${__("Error")}: <b>${errors.length}</b></p>`,
							];
							if (errors.length) {
								html.push(
									`<ul class="bac-import-errors">${errors
										.map(
											(e) =>
												`<li>${__("Baris")} ${e.row} · ${frappe.utils.escape_html(e.company || e.name || "")}: ${frappe.utils.escape_html(e.message || "")}</li>`
										)
										.join("")}</ul>`
								);
							}
							frappe.msgprint({
								title: __("Ringkasan Import"),
								indicator: errors.length ? "orange" : "green",
								message: html.join(""),
							});
						},
					});
				},
			});
			d.show();
		}

		_get_parent_target_config(target) {
			const map = {
				item: {
					doctype: "Item Default",
					parenttype: "Item",
					key: "item",
					msg: __("Pilih Item di filter terlebih dahulu"),
				},
				item_group: {
					doctype: "Item Default",
					parenttype: "Item Group",
					key: "item_group",
					msg: __("Pilih Item Group di filter terlebih dahulu"),
				},
				mode_of_payment: {
					doctype: "Mode of Payment Account",
					parenttype: "Mode of Payment",
					key: "mode_of_payment",
					msg: __("Pilih Mode of Payment di filter terlebih dahulu"),
				},
			};
			return map[target] || map.item_group;
		}

		copy_from_outlet_dialog() {
			const target = this.getTarget();
			const d = new frappe.ui.Dialog({
				title: __("Copy from Outlet"),
				fields: [
					{
						fieldname: "src_company",
						label: __("Company Sumber"),
						fieldtype: "Link",
						options: "Company",
						reqd: 1,
					},
					{
						fieldname: "dst_companies",
						label: __("Company Tujuan"),
						fieldtype: "MultiSelectList",
						get_data: (txt) => frappe.db.get_link_options("Company", txt),
						reqd: 1,
					},
				],
				primary_action_label: __("Lanjut"),
				primary_action: (vals) => {
					const src = vals.src_company;
					let dsts = vals.dst_companies;
					if (typeof dsts === "string") dsts = dsts.split(",").map((s) => s.trim()).filter(Boolean);
					if (!src || !dsts || !dsts.length) {
						frappe.msgprint(__("Harap pilih company sumber dan tujuan"));
						return;
					}

					const activeGroups = this._get_active_groups();
					const meta = this.field_meta[target] || [];
					const activeFields = meta.filter((f) => activeGroups.includes(f.group) && !f.read_only);
					const fieldnames = activeFields.map((f) => f.fieldname);

					if (target === "company") {
						frappe.db.get_value("Company", src, fieldnames, (r) => {
							const values = r || {};
							const changes = [];
							activeFields.forEach((f) => {
								const val = values[f.fieldname] || null;
								changes.push({
									name: src,
									company: src,
									field: f.fieldname,
									old: val,
									new: val,
								});
							});

							frappe.call({
								method: "account_bulk_config.api.propagation.preview_propagation",
								args: {
									target: target,
									changes: changes,
									targets: dsts,
								},
								freeze: true,
								callback: (res) => {
									d.hide();
									this._show_propagation_dialog(changes, res.message || [], "children", dsts);
								},
							});
						});
					} else {
						const cfg = this._get_parent_target_config(target);
						const filters =
							typeof this.get_export_filters === "function" ? this.get_export_filters() : {};
						const induk = filters[cfg.key];
						if (!induk) {
							frappe.msgprint(cfg.msg);
							return;
						}
						frappe.call({
							method: "frappe.client.get_value",
							args: {
								doctype: cfg.doctype,
								filters: { parenttype: cfg.parenttype, parent: induk, company: src },
								fieldname: fieldnames,
							},
							callback: (r) => {
								const values = r.message || {};
								const changes = [];
								activeFields.forEach((f) => {
									const val = values[f.fieldname] || null;
									changes.push({
										name: induk,
										company: src,
										field: f.fieldname,
										old: val,
										new: val,
									});
								});

								frappe.call({
									method: "account_bulk_config.api.propagation.preview_propagation",
									args: {
										target: target,
										changes: changes,
										targets: dsts,
									},
									freeze: true,
									callback: (res) => {
										d.hide();
										this._show_propagation_dialog(changes, res.message || [], "children", dsts);
									},
								});
							},
						});
					}
				},
			});
			d.show();
		}

		apply_to_children_dialog() {
			const target = this.getTarget();
			const d = new frappe.ui.Dialog({
				title: __("Terapkan ke anak…"),
				fields: [
					{
						fieldname: "group_company",
						label: __("Company Grup"),
						fieldtype: "Link",
						options: "Company",
						get_query: () => ({ filters: { is_group: 1 } }),
						reqd: 1,
					},
					{
						fieldname: "depth",
						label: __("Kedalaman"),
						fieldtype: "Select",
						options: [
							{ label: __("Anak langsung"), value: "children" },
							{ label: __("Semua turunan"), value: "all" },
						],
						default: "children",
					},
				],
				primary_action_label: __("Lanjut"),
				primary_action: (vals) => {
					const grp = vals.group_company;
					const depth = vals.depth || "children";
					if (!grp) {
						frappe.msgprint(__("Harap pilih company grup"));
						return;
					}

					const activeGroups = this._get_active_groups();
					const meta = this.field_meta[target] || [];
					const activeFields = meta.filter((f) => activeGroups.includes(f.group) && !f.read_only);
					const fieldnames = activeFields.map((f) => f.fieldname);

					if (target === "company") {
						frappe.db.get_value("Company", grp, fieldnames, (r) => {
							const values = r || {};
							const changes = [];
							activeFields.forEach((f) => {
								const val = values[f.fieldname] || null;
								changes.push({
									name: grp,
									company: grp,
									field: f.fieldname,
									old: val,
									new: val,
								});
							});

							frappe.call({
								method: "account_bulk_config.api.propagation.preview_propagation",
								args: {
									target: target,
									changes: changes,
									depth: depth,
								},
								freeze: true,
								callback: (res) => {
									d.hide();
									this._show_propagation_dialog(changes, res.message || [], depth);
								},
							});
						});
					} else {
						const cfg = this._get_parent_target_config(target);
						const filters =
							typeof this.get_export_filters === "function" ? this.get_export_filters() : {};
						const induk = filters[cfg.key];
						if (!induk) {
							frappe.msgprint(cfg.msg);
							return;
						}
						frappe.call({
							method: "frappe.client.get_value",
							args: {
								doctype: cfg.doctype,
								filters: { parenttype: cfg.parenttype, parent: induk, company: grp },
								fieldname: fieldnames,
							},
							callback: (r) => {
								const values = r.message || {};
								const changes = [];
								activeFields.forEach((f) => {
									const val = values[f.fieldname] || null;
									changes.push({
										name: induk,
										company: grp,
										field: f.fieldname,
										old: val,
										new: val,
									});
								});

								frappe.call({
									method: "account_bulk_config.api.propagation.preview_propagation",
									args: {
										target: target,
										changes: changes,
										depth: depth,
									},
									freeze: true,
									callback: (res) => {
										d.hide();
										this._show_propagation_dialog(changes, res.message || [], depth);
									},
								});
							},
						});
					}
				},
			});
			d.show();
		}
	}

	return BulkGrid;
});
