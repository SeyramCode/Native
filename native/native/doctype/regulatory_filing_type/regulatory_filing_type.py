# Copyright (c) 2026, Richmond Seyram and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from native.native.doctype.regulatory_filing_settings.regulatory_filing_settings import check_enabled


class RegulatoryFilingType(Document):
	def before_insert(self):
		check_enabled(_("create a Regulatory Filing Type"))

	def validate(self):
		if self.frequency == "Monthly":
			self.period_basis = "Calendar Year"
		self.validate_due_day()

	def validate_due_day(self):
		if not self.due_on_last_day and not 1 <= cint(self.due_day) <= 31:
			frappe.throw(
				_("Due Day of Month must be between 1 and 31, or tick Due on Last Day of Month."),
				title=_("Invalid Due Day"),
			)

