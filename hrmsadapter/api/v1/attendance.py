"""Attendance API — v1"""
import frappe
from frappe.utils import today

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_calendar(from_date=None, to_date=None):
	from frappe.utils import get_first_day, get_last_day

	from_date = from_date or str(get_first_day(today()))
	to_date = to_date or str(get_last_day(today()))

	try:
		data = frappe.call(
			"hrms.api.get_attendance_calendar_events",
			from_date=from_date,
			to_date=to_date,
		)
		return success(data=data or {})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def checkin(log_type, latitude=None, longitude=None, timestamp=None):
	"""Create an Employee Checkin record (for geo/manual check-in)."""
	if log_type not in ("IN", "OUT"):
		return error("log_type must be 'IN' or 'OUT'.", http_status_code=400)

	employee = get_current_employee()
	from frappe.utils import now_datetime

	checkin_time = timestamp or str(now_datetime())

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Employee Checkin",
				"employee": employee,
				"log_type": log_type,
				"time": checkin_time,
				"device_id": getattr(frappe.local, "mobile_device_id", None),
			}
		)
		if latitude and longitude:
			doc.latitude = float(latitude)
			doc.longitude = float(longitude)
		doc.insert()
		frappe.db.commit()
		return success(data={"name": doc.name, "log_type": log_type, "time": checkin_time})
	except frappe.ValidationError as e:
		return error(str(e), "VALIDATION_ERROR", http_status_code=422)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_attendance_requests(limit=20, offset=0):
	employee = get_current_employee()
	try:
		data = frappe.call(
			"hrms.api.get_attendance_requests",
			employee=employee,
		)
		items = (data or [])[int(offset): int(offset) + int(limit)]
		return success(data={"items": items, "total": len(data or [])})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def create_attendance_request(from_date, to_date, reason, half_day=0, half_day_date=None):
	employee = get_current_employee()
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Attendance Request",
				"employee": employee,
				"from_date": from_date,
				"to_date": to_date,
				"reason": reason,
				"half_day": int(half_day),
				"half_day_date": half_day_date,
			}
		)
		doc.insert()
		frappe.db.commit()
		return success(data={"name": doc.name})
	except frappe.ValidationError as e:
		return error(str(e), "VALIDATION_ERROR", http_status_code=422)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_shifts():
	employee = get_current_employee()
	try:
		data = frappe.get_all(
			"Shift Assignment",
			filters={"employee": employee, "status": "Active"},
			fields=["shift_type", "start_date", "end_date", "status"],
			order_by="start_date desc",
			limit=10,
		)
		return success(data=data or [])
	except Exception as e:
		return error(str(e), http_status_code=500)
