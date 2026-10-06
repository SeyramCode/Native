# Copyright (c) 2026, Richmond Seyram and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_date, get_link_to_form, getdate, nowdate

from native.native.doctype.regulatory_filing_settings.regulatory_filing_settings import (
	check_enabled,
	make_schedule_key,
)


class RegulatoryFiling(Document):
	def before_insert(self):
		check_enabled(_("create a Regulatory Filing"))

	def validate(self):
		self.validate_period()
		self.set_title()
		self.set_schedule_key()
		self.validate_duplicate()
		self.set_status()
		self.validate_filed_on()

	def validate_period(self):
		if self.period_start and self.period_end and getdate(self.period_end) < getdate(self.period_start):
			frappe.throw(_("Period End cannot be before Period Start."), title=_("Invalid Period"))

	def set_title(self):
		if not self.title:
			self.title = f"{self.filing_type} - {self.period_label}" if self.period_label else self.filing_type

	def set_schedule_key(self):
		self.schedule_key = (
			make_schedule_key(self.company, self.filing_type, self.period_start) if self.period_start else None
		)

	def validate_duplicate(self):
		if not self.schedule_key:
			return
		existing = frappe.db.get_value(
			"Regulatory Filing", {"schedule_key": self.schedule_key, "name": ["!=", self.name]}
		)
		if existing:
			frappe.throw(
				_("A {0} filing for {1} for the period starting {2} already exists: {3}").format(
					self.filing_type,
					self.company,
					format_date(self.period_start),
					get_link_to_form("Regulatory Filing", existing),
				),
				exc=frappe.DuplicateEntryError,
				title=_("Duplicate Filing"),
			)

	def set_status(self):
		if self.status != "Filed":
			self.status = "Overdue" if getdate(self.due_date) < getdate(nowdate()) else "Open"

	def validate_filed_on(self):
		if self.status == "Filed" and not self.filed_on:
			frappe.throw(_("Enter the <b>Filed On</b> date when marking a filing as Filed."), title=_("Missing Date"))
