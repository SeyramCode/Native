frappe.ui.form.on("Sales Order", {
	async refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		const sales_order = frm.doc.name;
		const { message } = await frappe.db.get_value(
			"Renewal Tracking",
			{ customer_po: sales_order, docstatus: ["<", 2] },
			"name"
		);
		// The form may have moved to another document while the lookup was running.
		if (message?.name || frm.doc.name !== sales_order || frm.doc.docstatus !== 1) return;

		frm.add_custom_button(
			__("Renewal Tracking"),
			() => {
				frappe.model.open_mapped_doc({
					method: "native.native.doctype.renewal_tracking.renewal_tracking.make_renewal_tracking",
					frm,
				});
			},
			__("Create")
		);
	},
});
