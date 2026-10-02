// Copyright (c) 2026, Richmond Seyram and contributors
// For license information, please see license.txt

frappe.ui.form.on('Customer Engagement Settings', {
	refresh(frm) {
		if (!frm.doc.enabled) {
			frm.dashboard.set_headline_alert(
				__('Customer Engagement is currently <strong>disabled</strong>.'),
				'yellow'
			);
		}
	}
});
