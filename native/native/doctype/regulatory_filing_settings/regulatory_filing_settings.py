# Copyright (c) 2026, Richmond Seyram and contributors
# For license information, please see license.txt

import hashlib
from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	cint,
	format_date,
	get_first_day,
	get_last_day,
	getdate,
	nowdate,
	strip_html,
)

SETTINGS = "Regulatory Filing Settings"
FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Annually": 12}
ERROR_LOG_PREFIX = "Regulatory Filing"
MAX_PERIODS_PER_RUN = 500
DAILY_JOB = f"{__name__}.run_daily"


class RegulatoryFilingSetupError(frappe.ValidationError):
	"""A setup problem the user can fix. `hint` says how."""

	def __init__(self, message, hint=None):
		super().__init__(message)
		self.hint = hint


class RegulatoryFilingRunError(Exception):
	"""Raised at the end of a scheduled run that had failures, so Scheduled Job Log shows it as Failed."""


class RegulatoryFilingSettings(Document):
	def validate(self):
		if self.enabled and self.auto_create and not self.generate_from:
			frappe.throw(
				_("Set <b>Generate Filings Due From</b> before enabling auto-creation."),
				title=_("Missing Start Date"),
			)


# --------------------------------------------------------------------------
# Master switch
# --------------------------------------------------------------------------


def is_enabled():
	return bool(cint(frappe.db.get_single_value(SETTINGS, "enabled")))


def check_enabled(action):
	"""Throw if the master switch is off. `action` completes "You cannot ..."."""
	if not is_enabled():
		frappe.throw(
			_("You cannot {0} because Regulatory Filing is disabled. Enable it in {1}.").format(
				action, frappe.utils.get_link_to_form(SETTINGS, SETTINGS)
			),
			title=_("Regulatory Filing Disabled"),
		)


# --------------------------------------------------------------------------
# Scheduler / manual entry points
# --------------------------------------------------------------------------


def run_daily():
	"""Daily scheduler entry point (see hooks.py).

	Every error is written to Error Log with details. If anything failed, an error is also
	raised at the end so Frappe records this run as Failed in Scheduled Job Log.
	"""
	try:
		_run_daily()
	except RegulatoryFilingRunError:
		raise  # details already in Error Log
	except Exception as e:
		frappe.db.rollback()
		_log_run_failure(e)
		raise


def _run_daily():
	if not is_enabled():
		return

	result = None
	if cint(frappe.db.get_single_value(SETTINGS, "auto_create")):
		result = create_due_filings()

	overdue_ok = mark_overdue_filings()

	problems = []
	if result and result["status"] in ("Failed", "Completed with Errors"):
		problems.append(result["summary"])
	if not overdue_ok:
		problems.append(_("Could not mark overdue filings."))

	# Read by generate_now(), which runs this through the Scheduled Job Type.
	frappe.flags.regulatory_filing_run = {"result": result, "overdue_ok": overdue_ok}

	if problems:
		raise RegulatoryFilingRunError(
			_("Regulatory Filing daily run had problems. Open Error Log and search for '{0}' for details and how to fix them.").format(
				ERROR_LOG_PREFIX
			)
			+ "\n\n"
			+ "\n".join(problems)
		)


@frappe.whitelist()
def generate_now():
	"""'Generate Now' button on Regulatory Filing Settings.

	Runs the daily job through its Scheduled Job Type (like its Execute button), so the run
	is recorded in Scheduled Job Log and counts as the job's last run.
	"""
	frappe.has_permission(SETTINGS, "write", throw=True)
	settings = frappe.get_single(SETTINGS)
	if not settings.enabled:
		check_enabled(_("generate filings"))
	if not settings.auto_create:
		frappe.throw(_("Enable Auto-Creation first."), title=_("Auto-Creation Disabled"))

	job_name = frappe.db.get_value("Scheduled Job Type", {"method": DAILY_JOB})
	if not job_name:
		frappe.throw(
			_("The daily job is not registered yet. Ask your administrator to run <code>bench migrate</code>."),
			title=_("Job Not Found"),
		)

	if not settings.generate_from:
		frappe.throw(
			_("Set <b>Generate Filings Due From</b> before generating filings."), title=_("Missing Start Date")
		)

	frappe.flags.regulatory_filing_run = None
	frappe.get_doc("Scheduled Job Type", job_name).execute()
	run = frappe.flags.regulatory_filing_run or {}
	result = run.get("result") or {}
	created = len(result.get("created") or [])
	error_log = f'<a href="/app/error-log">{_("Error Log")}</a>'

	problems = []
	if not result or result.get("status") == "Failed":
		problems.append(_("Auto-creation stopped with an unexpected error."))
	elif result.get("failed"):
		problems.append(_("{0} filing(s) could not be created.").format(result["failed"]))
	if run and not run.get("overdue_ok"):
		problems.append(_("Overdue filings could not be marked."))

	if problems:
		if created:
			problems.insert(0, _("Created {0} filing(s).").format(created))
		problems.append(_("Check the {0} for details and how to fix them.").format(error_log))
		crashed = not result or result.get("status") == "Failed"
		title = _("Auto-Creation Failed") if crashed else _("Auto-Creation Completed with Errors")
		frappe.throw("<br>".join(problems), title=title)

	if result.get("warnings"):
		frappe.msgprint(
			_("Created {0} filing(s), with warnings. Check the {1} for details.").format(created, error_log),
			title=_("Auto-Creation Completed with Warnings"),
			indicator="orange",
		)
	elif created:
		frappe.msgprint(
			_("Created {0} filing(s): {1}").format(created, ", ".join(result["created"])),
			title=_("Auto-Creation Complete"),
			indicator="green",
		)
	else:
		frappe.msgprint(
			_("No new filings were needed."), title=_("Auto-Creation Complete"), indicator="green"
		)


@frappe.whitelist()
def get_job_status():
	"""Whether the daily job has run yet, for the Settings form banner."""
	frappe.has_permission(SETTINGS, "read", throw=True)
	return frappe.db.get_value("Scheduled Job Type", {"method": DAILY_JOB}, ["name", "last_execution"], as_dict=True)


# --------------------------------------------------------------------------
# Auto-creation
# --------------------------------------------------------------------------


def create_due_filings():
	"""Create every filing that is due within `days_before_due` days and does not exist yet.

	Works on a window rather than an exact date, so any days missed while the server
	or scheduler was down are caught up on the next run. Safe to run repeatedly: each
	filing has a unique schedule key, so existing ones are skipped.
	"""
	settings = frappe.get_single(SETTINGS)
	if not settings.generate_from:
		summary = _("Nothing was created: set Generate Filings Due From in Regulatory Filing Settings.")
		return {"status": "Failed", "summary": summary, "created": [], "skipped": 0, "failed": 0}

	today = getdate(nowdate())
	horizon = add_days(today, cint(settings.days_before_due))
	generate_from = getdate(settings.generate_from)
	result = frappe._dict(created=[], skipped=0, failed=0, warnings={})

	try:
		filing_types = frappe.get_all(
			"Regulatory Filing Type", filters={"disabled": 0}, pluck="name", order_by="name"
		)
		for name in filing_types:
			filing_type = frappe.get_doc("Regulatory Filing Type", name)
			_create_for_company(filing_type, filing_type.company, generate_from, horizon, result)
	except Exception as e:
		frappe.db.rollback()
		_log_run_failure(e)
		summary = _("Auto-creation stopped with an unexpected error after creating {0} filing(s). See Error Log.").format(
			len(result.created)
		)
		return {"status": "Failed", "summary": summary, **result}

	if result.failed:
		status = "Completed with Errors"
	elif result.warnings:
		status = "Completed with Warnings"
	else:
		status = "Success"
	summary = _build_summary(result, today, horizon)
	return {"status": status, "summary": summary, **result}


def _create_for_company(filing_type, company, generate_from, horizon, result):
	try:
		periods = get_periods(filing_type, company, generate_from, horizon, result.warnings)
	except Exception as e:
		result.failed += 1
		_log_failure(filing_type.name, company, None, e)
		return

	for period in periods:
		key = make_schedule_key(company, filing_type.name, period.start)
		if frappe.db.exists("Regulatory Filing", {"schedule_key": key}):
			result.skipped += 1
			continue

		try:
			doc = frappe.get_doc(
				{
					"doctype": "Regulatory Filing",
					"filing_type": filing_type.name,
					"company": company,
					"period_start": period.start,
					"period_end": period.end,
					"period_label": period.label,
					"due_date": period.due_date,
					"auto_created": 1,
				}
			)
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			result.created.append(doc.name)
		except frappe.DuplicateEntryError:
			# Created by another run at the same moment; nothing to do.
			frappe.db.rollback()
			frappe.clear_messages()
			result.skipped += 1
		except Exception as e:
			frappe.db.rollback()
			frappe.clear_messages()
			result.failed += 1
			_log_failure(filing_type.name, company, period, e)


# --------------------------------------------------------------------------
# Period and due date calculation
# --------------------------------------------------------------------------


def get_periods(filing_type, company, generate_from, horizon, warnings=None):
	"""Return periods whose due date falls between `generate_from` and `horizon` (inclusive)."""
	length = FREQUENCY_MONTHS.get(filing_type.frequency)
	if not length:
		raise RegulatoryFilingSetupError(
			_("Filing type {0} has no valid Frequency.").format(filing_type.name),
			hint=_("Open the filing type and choose a Frequency (Monthly, Quarterly, Half-Yearly or Annually)."),
		)

	anchor = get_period_anchor(filing_type, company, warnings)
	months_after = cint(filing_type.months_after_period_end)

	# Start far enough back that no period due on/after generate_from is missed.
	lookback = add_months(generate_from, -(length + months_after + 1))
	index = _months_between(anchor, lookback) // length

	periods = []
	for _i in range(MAX_PERIODS_PER_RUN):
		start = getdate(add_months(anchor, index * length))
		end = add_days(add_months(anchor, (index + 1) * length), -1)
		due_date = get_due_date(filing_type, end)
		index += 1

		if due_date > horizon:
			break
		if due_date >= generate_from:
			periods.append(
				frappe._dict(
					start=start, end=end, due_date=due_date, label=get_period_label(filing_type, start, end)
				)
			)
	return periods


def get_period_anchor(filing_type, company, warnings=None):
	"""A date that periods line up with: 1 Jan, or the start of the company's fiscal year.

	Only the fiscal year's start month/day matters for alignment, so if no Fiscal Year
	covers today, the company's most recent one is used and a warning is recorded.
	`warnings` is a per-run dict ({company: message}) so each company is warned once.
	"""
	if filing_type.frequency == "Monthly" or filing_type.period_basis != "Fiscal Year":
		return date(getdate(nowdate()).year, 1, 1)

	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	today = nowdate()
	try:
		return getdate(get_fiscal_year(today, company=company, verbose=0)[1])
	except FiscalYearError:
		pass

	latest = _get_latest_fiscal_year(company)
	if not latest:
		raise RegulatoryFilingSetupError(
			_("Company {0} has no Fiscal Year at all, so {1} periods cannot be worked out.").format(
				company, filing_type.name
			),
			hint=_(
				"Create a Fiscal Year for {0} (Accounting > Fiscal Year), "
				"or change the filing type's Period Basis to Calendar Year."
			).format(company),
		)

	if warnings is not None and company not in warnings:
		warnings[company] = _(
			"No Fiscal Year covers today ({0}) for {1}. Periods were lined up using its latest "
			"Fiscal Year, {2} (starting {3}), so filings are still created."
		).format(format_date(today), company, latest.name, format_date(latest.year_start_date))
		_log_warning(company, warnings[company])

	return getdate(latest.year_start_date)


def _get_latest_fiscal_year(company):
	"""Most recent enabled Fiscal Year that applies to `company` (no companies listed = all)."""
	fiscal_years = frappe.get_all(
		"Fiscal Year",
		filters={"disabled": 0},
		fields=["name", "year_start_date"],
		order_by="year_start_date desc",
	)
	for fy in fiscal_years:
		companies = frappe.get_all("Fiscal Year Company", filters={"parent": fy.name}, pluck="company")
		if not companies or company in companies:
			return fy
	return None


def get_due_date(filing_type, period_end):
	due_month = add_months(get_first_day(period_end), cint(filing_type.months_after_period_end))
	last_day = get_last_day(due_month)
	if filing_type.due_on_last_day:
		return last_day
	return date(last_day.year, last_day.month, min(cint(filing_type.due_day), last_day.day))


def get_period_label(filing_type, start, end):
	if filing_type.frequency == "Monthly":
		return start.strftime("%b %Y")
	if filing_type.frequency == "Annually" and start.month == 1:
		return str(start.year)
	return f"{start.strftime('%b %Y')} - {end.strftime('%b %Y')}"


def make_schedule_key(company, filing_type, period_start):
	raw = f"{company}|{filing_type}|{getdate(period_start)}"
	return hashlib.sha1(raw.encode()).hexdigest()


def _months_between(a, b):
	return (b.year - a.year) * 12 + (b.month - a.month)


# --------------------------------------------------------------------------
# Overdue marking
# --------------------------------------------------------------------------


def mark_overdue_filings():
	"""Set Open filings past their due date to Overdue. Returns False if it failed."""
	try:
		names = frappe.get_all(
			"Regulatory Filing",
			filters={"status": "Open", "due_date": ["<", nowdate()]},
			pluck="name",
		)
		for name in names:
			frappe.db.set_value("Regulatory Filing", name, "status", "Overdue")
		frappe.db.commit()
		return True
	except Exception as e:
		frappe.db.rollback()
		_log_error(
			title=_("{0}: could not mark overdue filings").format(ERROR_LOG_PREFIX),
			what=_("The daily job could not change Open filings past their due date to Overdue."),
			error=e,
			hint=_("Statuses will be corrected on the next daily run or when a filing is saved."),
		)
		return False


# --------------------------------------------------------------------------
# Run summary and error logging
# --------------------------------------------------------------------------


def _build_summary(result, today, horizon):
	lines = [
		_("Checked filings due up to {0} (today is {1}).").format(format_date(horizon), format_date(today))
	]
	if result.created:
		shown = ", ".join(result.created[:10])
		more = _(" and {0} more").format(len(result.created) - 10) if len(result.created) > 10 else ""
		lines.append(_("Created {0} filing(s): {1}{2}.").format(len(result.created), shown, more))
	else:
		lines.append(_("No new filings were needed."))
	if result.skipped:
		lines.append(_("Skipped {0} that already exist.").format(result.skipped))
	for message in result.warnings.values():
		lines.append(_("Warning: {0}").format(message))
	if result.failed:
		lines.append(
			_("{0} could not be created. Open Error Log and search for '{1}' to see why.").format(
				result.failed, ERROR_LOG_PREFIX
			)
		)
	return "\n".join(lines)


def _log_failure(filing_type, company, period, error):
	if period:
		title = _("{0}: could not create {1} for {2} ({3})").format(
			ERROR_LOG_PREFIX, filing_type, company, period.label
		)
		what = _(
			"Auto-creation could not create the '{0}' filing for {1}, period {2} ({3} to {4}), due {5}."
		).format(
			filing_type,
			company,
			period.label,
			format_date(period.start),
			format_date(period.end),
			format_date(period.due_date),
		)
	else:
		title = _("{0}: could not work out periods for {1} ({2})").format(
			ERROR_LOG_PREFIX, filing_type, company
		)
		what = _("Auto-creation could not work out the filing periods for '{0}' for {1}.").format(
			filing_type, company
		)

	_log_error(
		title=title,
		what=what,
		error=error,
		hint=_hint_for(error, filing_type),
		reference_doctype="Regulatory Filing Type",
		reference_name=filing_type,
	)


def _log_warning(company, message):
	frappe.log_error(
		title=_("{0} (warning): no current Fiscal Year for {1}").format(ERROR_LOG_PREFIX, company)[:140],
		message="\n\n".join(
			[
				_("WHAT HAPPENED"),
				message,
				_("IMPACT"),
				_("None yet. Filings were created normally. This is a reminder only."),
				_("HOW TO FIX"),
				_(
					"Create the current Fiscal Year for {0} (Accounting > Fiscal Year). "
					"ERPNext also needs it before transactions can be posted in the new year."
				).format(company),
			]
		),
		reference_doctype="Company",
		reference_name=company,
	)
	frappe.db.commit()


def _log_run_failure(error):
	_log_error(
		title=_("{0}: auto-creation run failed").format(ERROR_LOG_PREFIX),
		what=_("The auto-creation run stopped part-way. Filings created before the error were kept."),
		error=error,
		hint=_("This is unexpected. Share this log with your developer."),
	)


def _hint_for(error, filing_type):
	if isinstance(error, RegulatoryFilingSetupError) and error.hint:
		return error.hint
	if isinstance(error, frappe.LinkValidationError):
		return _(
			"A linked record (company or filing type) no longer exists or was renamed. "
			"Check the Company set on filing type '{0}'."
		).format(filing_type)
	if isinstance(error, frappe.MandatoryError):
		return _("A required field on Regulatory Filing is empty. If required fields were added recently, give them a default value.")
	if isinstance(error, frappe.ValidationError):
		return _("A validation rule on Regulatory Filing rejected the record. The reason above explains which one.")
	return _("This is unexpected. Share this log with your developer.")


def _log_error(title, what, error, hint, reference_doctype=None, reference_name=None):
	reason = strip_html(str(error)).strip() or error.__class__.__name__
	message = "\n\n".join(
		[
			_("WHAT HAPPENED"),
			what,
			_("REASON"),
			reason,
			_("HOW TO FIX"),
			hint,
			_(
				"Once fixed, nothing else is needed: the next daily run retries automatically. "
				"To retry now, click Generate Now in Regulatory Filing Settings."
			),
			"-" * 60,
			_("TECHNICAL DETAILS (for developers)"),
			frappe.get_traceback(),
		]
	)
	frappe.log_error(
		title=title[:140],
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
	frappe.db.commit()
