from frappe import _


def get_data():
	return {
		"fieldname": "customer_engagement",
		"transactions": [
			{"label": _("Support"), "items": ["Issue"]},
			{"label": _("Project"), "items": ["Project"]},
		],
		"internal_links": {
			"Project": "project",
		},
	}
