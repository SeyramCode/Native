import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form

FEEDBACK_FIELDS = [
	"feedback",
	"reviewer",
	"user",
	"owner",
	"reviewer_name",
	"reviewer_designation",
	"added_on",
	"employee",
	"total_score",
	"name",
]

# What a direct manager may do with a reportee's appraisal: view, never change.
MANAGER_PTYPES = {"read", "select", "print", "email", "report", "export"}


@frappe.whitelist()
def get_feedback_history(employee: str, appraisal: str):
	"""Override of hrms get_feedback_history for the Appraisal's Feedback tab.

	HR Manager gets every review with the reviewer. Everyone else who can read
	the appraisal (the appraisee and the direct manager, see
	has_appraisal_permission) gets every review without the reviewer: the
	server never sends who wrote it, so the stock HRMS tab shows it as is.

	`employee` is kept for the HRMS signature but ignored: the appraisee is read
	from the appraisal, so a caller cannot ask for another employee's feedback.
	"""
	frappe.has_permission("Appraisal", "read", appraisal, throw=True)

	appraisee = frappe.db.get_value("Appraisal", appraisal, "employee")
	filters = {"employee": appraisee, "appraisal": appraisal, "docstatus": 1}

	if is_hr(frappe.session.user):
		feedback = frappe.get_list(
			"Employee Performance Feedback", filters=filters, fields=FEEDBACK_FIELDS, order_by="added_on desc"
		)
	else:
		feedback = [
			anonymise(f)
			for f in frappe.get_all(
				"Employee Performance Feedback",
				filters=filters,
				fields=FEEDBACK_FIELDS,
				order_by="added_on desc",
			)
		]

	return frappe._dict(
		feedback_history=feedback,
		reviews_per_rating=get_reviews_per_rating(feedback),
		avg_feedback_score=frappe.db.get_value("Appraisal", appraisal, "avg_feedback_score"),
	)


def get_feedback_permission_query(user=None):
	"""List/report filter for Employee Performance Feedback.

	Below HR Manager, a user only sees feedback they created. The Feedback tab
	is not affected: it reads through get_all.
	"""
	user = user or frappe.session.user
	if is_hr(user):
		return ""
	return f"`tabEmployee Performance Feedback`.owner = {frappe.db.escape(user)}"


def has_feedback_permission(doc, ptype=None, user=None):
	"""Record-level check matching get_feedback_permission_query.

	Returns False to deny, None to leave the decision to roles and user permissions.
	"""
	user = user or frappe.session.user
	if is_hr(user) or doc.is_new() or doc.owner == user:
		return None
	return False


def get_appraisal_permission_query(user=None):
	"""List/report filter for Appraisal.

	Below HR Manager, a user only sees their own appraisal and those of
	employees who report to them. Appraisal.employee ignores user permissions
	(see native.patches.secure_appraisal_scores), so this is the only filter.
	"""
	user = user or frappe.session.user
	if is_hr(user):
		return ""

	employees = get_user_employees(user)
	if not employees:
		return "1=0"

	mine = ", ".join(frappe.db.escape(e) for e in employees)
	return (
		f"(`tabAppraisal`.employee in ({mine})"
		f" or `tabAppraisal`.employee in (select name from `tabEmployee` where reports_to in ({mine})))"
	)


def has_appraisal_permission(doc, ptype=None, user=None):
	"""Record-level check matching get_appraisal_permission_query.

	The appraisee keeps what their roles allow. The direct manager may only view.
	"""
	user = user or frappe.session.user
	if is_hr(user) or not doc.employee:
		return None

	mine = get_user_employees(user)
	if doc.employee in mine:
		return None
	if (ptype or "read") in MANAGER_PTYPES and frappe.db.get_value(
		"Employee", doc.employee, "reports_to"
	) in mine:
		return None
	return False


def validate_feedback_reviewer(doc, method=None):
	"""Employee Performance Feedback validate.

	HRMS only stops self-review, so anyone could post a review in a colleague's
	name. Below HR Manager, the reviewer must be the submitter.
	"""
	if is_hr(frappe.session.user):
		return
	if doc.reviewer not in get_user_employees(frappe.session.user):
		frappe.throw(
			_("You can only give feedback as yourself. Set {0} to your own Employee record.").format(
				frappe.bold(_("Reviewer"))
			),
			title=_("Reviewer Must Be You"),
		)


def validate_single_feedback_per_reviewer(doc, method=None):
	"""Employee Performance Feedback before_submit.

	One submitted review per reviewer per appraisal, so nobody can pull an
	average (and the final score) by submitting the same review many times.
	"""
	existing = frappe.db.exists(
		"Employee Performance Feedback",
		{"appraisal": doc.appraisal, "reviewer": doc.reviewer, "docstatus": 1, "name": ["!=", doc.name]},
	)
	if existing:
		frappe.throw(
			_(
				"{0} has already submitted feedback {1} for appraisal {2}. Cancel it before submitting a new one."
			).format(
				frappe.bold(doc.reviewer_name or doc.reviewer),
				get_link_to_form("Employee Performance Feedback", existing),
				frappe.bold(doc.appraisal),
			),
			title=_("Duplicate Feedback"),
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_appraisals_for_feedback(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
):
	"""Appraisal picker on the feedback form.

	Peers cannot read other people's appraisals, so the standard link search
	finds nothing. This returns only the name and cycle of the chosen
	employee's appraisals in an In Progress cycle, never any scores.
	"""
	frappe.has_permission("Employee Performance Feedback", "create", throw=True)

	# a filter list such as ["!=", ""] here would match every employee
	employee = filters.get("employee") if isinstance(filters, dict) else None
	if not isinstance(employee, str) or not employee:
		return []

	cycles = frappe.get_all("Appraisal Cycle", filters={"status": "In Progress"}, pluck="name")
	if not cycles:
		return []

	return frappe.get_all(
		"Appraisal",
		filters={
			"employee": employee,
			"appraisal_cycle": ["in", cycles],
			"docstatus": ["<", 2],
			"name": ["like", f"%{txt}%"],
		},
		fields=["name", "appraisal_cycle"],
		order_by="creation desc",
		start=start,
		page_length=page_len,
		as_list=True,
	)


@frappe.whitelist()
def get_feedback_details(employee: str, appraisal: str | None = None):
	"""Values the feedback form normally fetches from Employee and Appraisal.

	Reviewers cannot read a colleague's Employee or Appraisal record, so the
	browser's link fetch comes back empty and the required Company field
	blocks Save. Only for an employee with an appraisal in an In Progress
	cycle. The server fetches the same values again on save.
	"""
	frappe.has_permission("Employee Performance Feedback", "create", throw=True)
	if not isinstance(employee, str) or (appraisal is not None and not isinstance(appraisal, str)):
		frappe.throw(_("Employee and Appraisal must be single values."), title=_("Invalid Feedback Details"))

	cycles = frappe.get_all("Appraisal Cycle", filters={"status": "In Progress"}, pluck="name")
	if not cycles:
		return {}

	filters = {"employee": employee, "appraisal_cycle": ["in", cycles], "docstatus": ["<", 2]}
	if appraisal:
		filters["name"] = appraisal
	open_appraisal = frappe.get_all("Appraisal", filters=filters, fields=["appraisal_cycle"], limit=1)
	if not open_appraisal:
		return {}

	# only what the form needs before save; department and designation are fetched on save
	details = frappe.db.get_value("Employee", employee, ["employee_name", "company"], as_dict=True)
	if appraisal:
		details.appraisal_cycle = open_appraisal[0].appraisal_cycle
	return details


def check_hrms_compatibility():
	"""after_migrate: report anything an HRMS upgrade removed that this module relies on.

	Hooks keyed on a renamed method, doctype, field or report stop working
	without any error, which would quietly reopen the score leaks.
	"""
	problems = []
	try:
		frappe.get_attr("hrms.hr.doctype.appraisal.appraisal.get_feedback_history")
	except (ImportError, AttributeError):
		problems.append("hrms get_feedback_history is gone: the Feedback tab override no longer applies.")

	required_fields = {
		"Appraisal": ["employee", "avg_feedback_score"],
		"Employee Performance Feedback": ["employee", "reviewer", "appraisal", "total_score"],
		"Employee": ["reports_to", "user_id"],
	}
	for doctype, fields in required_fields.items():
		if not frappe.db.exists("DocType", doctype):
			problems.append(f"DocType {doctype} is gone.")
			continue
		meta = frappe.get_meta(doctype)
		problems += [f"{doctype}.{f} is gone." for f in fields if not meta.has_field(f)]

	if not frappe.db.exists("Custom Role", {"report": "Appraisal Overview"}):
		problems.append(
			"Appraisal Overview is no longer restricted to HR Manager. Run native.patches.secure_appraisal_scores."
		)

	if problems:
		message = "\n".join(problems)
		frappe.log_error(title="native: 360 appraisal permissions need review", message=message)
		print(f"WARNING native 360 appraisal:\n{message}")


def is_hr(user):
	return "HR Manager" in frappe.get_roles(user)


def get_user_employees(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def anonymise(feedback):
	"""Keep the rating, comment and date; drop everything that identifies the reviewer.

	`user` is set too: the HRMS card builds its avatar from it and, when empty,
	falls back to the viewer's own initials.
	"""
	return frappe._dict(
		name="",
		feedback=feedback.feedback,
		total_score=feedback.total_score,
		added_on=feedback.added_on,
		reviewer_name=_("Reviewer"),
		user=_("Reviewer"),
	)


def get_reviews_per_rating(feedback):
	"""Percentage of reviews per star rating, 1 to 5."""
	reviews_per_rating = []
	for i in range(1, 6):
		count = sum(1 for f in feedback if i <= flt(f.total_score) <= i + 0.99)
		reviews_per_rating.append(flt((count / len(feedback)) * 100, 0) if feedback else 0)
	return reviews_per_rating
