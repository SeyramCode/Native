// Copyright (c) 2026, Richmond Gedziq and contributors
// For license information, please see license.txt

function sync_engagement_contact(frm) {
	const emails = (frm.doc.contacts || [])
		.map(r => r.contact_email)
		.filter(Boolean)
		.join(', ');
	frm.set_value('engagement_contact', emails);
}

frappe.ui.form.on('Customer Engagement', {
	refresh(frm) {
		sync_engagement_contact(frm);

		frappe.db.get_single_value('Customer Engagement Settings', 'enabled').then(enabled => {
			if (!enabled) {
				frm.dashboard.set_headline_alert(
					__('Customer Engagement is <strong>disabled</strong>. Enable it in <a href="/app/customer-engagement-settings">Settings</a>.'),
					'yellow'
				);
				frm.disable_save();
			}
		});

		frm.set_query('contact_person', 'contacts', () => ({
			query: 'frappe.contacts.doctype.contact.contact.contact_query',
			filters: {
				link_doctype: 'Customer',
				link_name: frm.doc.customer
			}
		}));

		frm.set_query('project', () => ({
			filters: { customer: frm.doc.customer }
		}));

		frm.set_query('issue', () => ({
			filters: { customer: frm.doc.customer }
		}));

		if (!frm.doc.__islocal) {
			frm.add_custom_button(__('Email'), () => {
				const recipients = (frm.doc.contacts || [])
					.map(r => r.contact_email)
					.filter(Boolean)
					.join(', ');

				new frappe.views.CommunicationComposer({
					doc: frm.doc,
					frm: frm,
					recipients: recipients,
					subject: frm.doc.title,
					attach_document_print: false,
				});
			}, __('Create'));

			frm.add_custom_button(__('Issue'), () => {
				frappe.new_doc('Issue', {
					subject: frm.doc.title,
					customer: frm.doc.customer,
					customer_engagement: frm.doc.name,
					project: frm.doc.project || '',
				});
			}, __('Create'));
		}

		if (!frm.doc.__islocal && frm.doc.activity_status !== 'Completed' && frm.doc.activity_status !== 'Cancelled') {
			frm.add_custom_button(__('Mark Completed'), () => {
				frm.set_value('activity_status', 'Completed');
				frm.save();
			});
		}
	},

	customer(frm) {
		frm.set_value('contacts', []);
		frm.set_value('project', '');
		frm.set_value('issue', '');
		sync_engagement_contact(frm);
	}
});

frappe.ui.form.on('Customer Engagement Contact', {
	contact_email(frm) {
		sync_engagement_contact(frm);
	},
	contacts_remove(frm) {
		sync_engagement_contact(frm);
	}
});
