from frappe import _


def get_dashboard_data(data):
	# Show Renewal Tracking under the Reference group on the Sales Order dashboard.
	data.setdefault("non_standard_fieldnames", {})["Renewal Tracking"] = "customer_po"

	for group in data["transactions"]:
		if group["label"] == _("Reference"):
			group["items"].append("Renewal Tracking")
			return data

	data["transactions"].append({"label": _("Reference"), "items": ["Renewal Tracking"]})
	return data
