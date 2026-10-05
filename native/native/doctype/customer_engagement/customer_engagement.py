# Copyright (c) 2026, Richmond Gedziq and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CustomerEngagement(Document):
	def validate(self):
		emails = [row.contact_email for row in self.contacts if row.contact_email]
		self.engagement_contact = ", ".join(emails)

	def before_insert(self):
		if not frappe.get_single_value("Customer Engagement Settings", "enabled"):
			frappe.throw(
				frappe._("Customer Engagement is disabled. Enable it in Customer Engagement Settings."),
				title=frappe._("Feature Disabled"),
			)
		if not self.account_manager:
			self.account_manager = frappe.session.user
