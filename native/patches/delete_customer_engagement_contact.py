import frappe


def execute():
	frappe.delete_doc("DocType", "Customer Engagement Contact", ignore_missing=True, force=True)
