// Copyright (c) 2026, Richmond Seyram and contributors
// For license information, please see license.txt

frappe.listview_settings["Regulatory Filing"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { Open: "orange", Filed: "green", Overdue: "red" };
		return [__(doc.status), colors[doc.status], "status,=," + doc.status];
	},
};
