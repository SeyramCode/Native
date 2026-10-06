// Copyright (c) 2026, Richmond Seyram and contributors
// For license information, please see license.txt

const SETTINGS_MODULE = "native.native.doctype.regulatory_filing_settings.regulatory_filing_settings";

frappe.ui.form.on("Regulatory Filing Settings", {
	refresh(frm) {
		if (!frm.doc.enabled) {
			frm.dashboard.set_headline_alert(
				__("Regulatory Filing is currently <strong>disabled</strong>."),
				"yellow"
			);
			return;
		}

		if (!frm.doc.auto_create) return;

		frm.add_custom_button(__("Generate Now"), () => generate_now(frm));

		frappe.call(`${SETTINGS_MODULE}.get_job_status`).then(({ message: job }) => {
			if (job && !job.last_execution) {
				frm.dashboard.set_headline_alert(
					__("The daily auto-creation job has not run yet. Click <b>Generate Now</b> to run it immediately."),
					"blue"
				);
				frm.change_custom_button_type(__("Generate Now"), null, "primary");
			}
		});
	},
});

function generate_now(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the settings first."));
		return;
	}
	frappe.call({
		method: `${SETTINGS_MODULE}.generate_now`,
		freeze: true,
		freeze_message: __("Creating due filings..."),
		always() {
			frm.reload_doc();
		},
	});
}
