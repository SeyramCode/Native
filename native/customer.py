from frappe import _


def get_dashboard_data(data):
	# Show Customer Engagement on the Customer dashboard, after the standard groups.
	data["transactions"].append({"label": _("Engagement"), "items": ["Customer Engagement"]})
	return data
