"""Database settings for the 360 appraisal permissions in native.appraisal.

Safe to run more than once.

- Appraisal.employee and Employee Performance Feedback.employee ignore user
  permissions. Permission hooks can only deny access, never grant it, so
  without this a manager cannot open a reportee's appraisal and a peer cannot
  give feedback. Access is then decided by the hooks in native.appraisal.
- The Appraisal Overview report lists every employee's scores without any
  permission filter, so only HR Manager may run it.
"""

import frappe

MODULE = "Native"
REPORT = "Appraisal Overview"


def execute():
	for doctype in ("Appraisal", "Employee Performance Feedback"):
		ignore_user_permissions_on_employee(doctype)
	restrict_report_to_hr_manager()


def ignore_user_permissions_on_employee(doctype):
	name = f"{doctype}-employee-ignore_user_permissions"
	if frappe.db.exists("Property Setter", name):
		frappe.db.set_value("Property Setter", name, "value", "1")
		# set_value skips Property Setter.on_update, which clears the cached meta
		frappe.clear_cache(doctype=doctype)
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"name": name,
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": "employee",
			"property": "ignore_user_permissions",
			"property_type": "Check",
			"value": "1",
			"module": MODULE,
		}
	).insert(ignore_permissions=True)


def restrict_report_to_hr_manager():
	name = frappe.db.get_value("Custom Role", {"report": REPORT})
	doc = frappe.get_doc("Custom Role", name) if name else frappe.new_doc("Custom Role")
	doc.report = REPORT
	doc.ref_doctype = "Appraisal"
	doc.set("roles", [{"role": "HR Manager"}])
	doc.save(ignore_permissions=True)
