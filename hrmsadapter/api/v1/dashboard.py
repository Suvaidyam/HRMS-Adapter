"""Dashboard API — v1"""
import frappe
from frappe.utils import get_first_day, get_last_day, today

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import success
from hrmsadapter.utils.validators import get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_dashboard_data(widgets=None):
	"""
	Return all dashboard widgets in one request.
	widgets: comma-separated or JSON list — if omitted, return all.
	"""
	import json

	if isinstance(widgets, str):
		try:
			widgets = json.loads(widgets)
		except Exception:
			widgets = [w.strip() for w in widgets.split(",") if w.strip()]
	if not widgets:
		widgets = ["attendance", "leave_balance", "pending_approvals",
				   "holidays", "birthdays", "announcements"]

	result = {}
	for widget in widgets:
		try:
			fn = _WIDGET_MAP.get(widget)
			result[widget] = fn() if fn else {"error": "unknown widget"}
		except Exception as e:
			result[widget] = {"error": str(e)}

	return success(data=result)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_quick_actions():
	settings = frappe.get_cached_doc("HRMS Mobile Settings")
	actions = []
	if settings.enable_leave:
		actions.append({"id": "apply_leave", "label": "Apply Leave", "icon": "calendar"})
	if settings.enable_attendance and settings.enable_checkin:
		actions.append({"id": "checkin", "label": "Check In/Out", "icon": "clock"})
	if settings.enable_expense:
		actions.append({"id": "new_expense", "label": "New Expense", "icon": "receipt"})
	if settings.enable_approvals:
		actions.append({"id": "approvals", "label": "Pending Approvals", "icon": "check-circle"})
	return success(data=actions)


# ---------------------------------------------------------------------------
# Widget implementations
# ---------------------------------------------------------------------------

def _attendance_widget():
	from frappe.utils import get_first_day, get_last_day, today
	try:
		data = frappe.call(
			"hrms.api.get_attendance_calendar_events",
			from_date=str(get_first_day(today())),
			to_date=str(get_last_day(today())),
		)
		return data or {}
	except Exception:
		return {}


def _leave_balance_widget():
	employee = get_current_employee()
	try:
		return frappe.call("hrms.api.get_leave_balance_map", employee=employee) or {}
	except Exception:
		return {}


def _pending_approvals_widget():
	from hrmsadapter.api.v1.approval import APPROVAL_DOCTYPES

	user = frappe.session.user
	count = 0
	for config in APPROVAL_DOCTYPES:
		if not frappe.has_permission(config["doctype"], "read"):
			continue
		filters = {config["status_field"]: ("in", config["pending_values"])}
		if config["approver_field"]:
			filters[config["approver_field"]] = user
		try:
			count += frappe.db.count(config["doctype"], filters)
		except Exception:
			pass
	return {"count": count}


def _holidays_widget():
	employee = get_current_employee()
	try:
		return frappe.call(
			"hrms.api.get_holidays_for_employee",
			employee=employee,
			from_date=str(today()),
			to_date=str(get_last_day(today())),
		) or []
	except Exception:
		return []


def _birthdays_widget():
	from frappe.utils import add_to_date

	today_str = today()
	next_30 = str(add_to_date(today_str, days=30))
	company = frappe.db.get_default("company")
	employees = frappe.db.sql(
		"""
		SELECT employee_name, date_of_birth, image
		FROM `tabEmployee`
		WHERE company = %s
		  AND status = 'Active'
		  AND DATE_FORMAT(date_of_birth, '%%m-%%d') BETWEEN DATE_FORMAT(%s, '%%m-%%d')
		    AND DATE_FORMAT(%s, '%%m-%%d')
		LIMIT 10
		""",
		(company, today_str, next_30),
		as_dict=True,
	)
	return employees or []


def _announcements_widget():
	return frappe.get_all(
		"Announcement",
		filters={"publish": 1},
		fields=["name", "title", "description", "publish_from", "publish_to"],
		order_by="publish_from desc",
		limit=5,
	) if frappe.db.table_exists("tabAnnouncement") else []


_WIDGET_MAP = {
	"attendance": _attendance_widget,
	"leave_balance": _leave_balance_widget,
	"pending_approvals": _pending_approvals_widget,
	"holidays": _holidays_widget,
	"birthdays": _birthdays_widget,
	"announcements": _announcements_widget,
}
