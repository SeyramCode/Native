// Reviewers cannot read a colleague's Employee or Appraisal record (native.appraisal
// permission hooks), so the standard link search and fetched values come back empty.
// - The Appraisal picker uses a search that returns only the employee's appraisals in
//   an In Progress cycle, without scores.
// - Employee name, company (required) and appraisal cycle are filled from
//   native.appraisal.get_feedback_details; the server fetches them again on save.
// These handlers run after the HRMS ones, so they replace its Appraisal set_query.

// HRMS loads the feedback criteria the moment Appraisal changes, including when it
// clears Appraisal after an Employee change. For a reviewer, Company is still empty
// then (the link fetch cannot read the colleague's Employee record), and with strict
// user permissions the unsaved form is not readable, so the call fails with
// "Not permitted". The HRMS handlers are kept and run after the details are filled,
// only once an appraisal is chosen.
const hrms_appraisal_handlers = frappe.ui.form
	.get_event_handler_list("Employee Performance Feedback", "appraisal")
	.slice();
frappe.ui.form.off("Employee Performance Feedback", "appraisal");

frappe.ui.form.on("Employee Performance Feedback", {
	refresh(frm) {
		frm.set_query("appraisal", () => ({
			query: "native.appraisal.get_appraisals_for_feedback",
			filters: { employee: frm.doc.employee },
		}));
	},

	employee(frm) {
		native_fill_feedback_details(frm);
	},

	async appraisal(frm) {
		await native_fill_feedback_details(frm);
		if (frm.doc.appraisal) {
			for (const handler of hrms_appraisal_handlers) await handler(frm);
		}
	},
});

async function native_fill_feedback_details(frm) {
	if (!frm.doc.employee || frm.doc.docstatus !== 0) return;

	const { message } = await frappe.call("native.appraisal.get_feedback_details", {
		employee: frm.doc.employee,
		appraisal: frm.doc.appraisal || null,
	});
	if (message && Object.keys(message).length) await frm.set_value(message);
}
