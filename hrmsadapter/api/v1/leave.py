"""Leave Management API — v1"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import clamp_pagination, get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_applications(for_approval=0, limit=20, offset=0):
	limit, offset = clamp_pagination(limit, offset)
	employee = get_current_employee()
	try:
		data = frappe.call(
			"hrms.api.get_leave_applications",
			employee=employee,
			for_approval=int(for_approval),
			limit=limit + offset,
		)
		items = data[offset: offset + limit] if data else []
		return success(data={"items": items, "total": len(data or []), "limit": limit, "offset": offset})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_balance():
	employee = get_current_employee()
	try:
		data = frappe.call("hrms.api.get_leave_balance_map", employee=employee)
		return success(data=data or {})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_types():
	employee = get_current_employee()
	try:
		data = frappe.call("hrms.api.get_leave_types", employee=employee)
		return success(data=data or [])
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_holidays(from_date=None, to_date=None):
	from frappe.utils import get_first_day, get_last_day, today

	from_date = from_date or str(get_first_day(today()))
	to_date = to_date or str(get_last_day(today()))
	employee = get_current_employee()

	try:
		data = frappe.call(
			"hrms.api.get_holidays_for_employee",
			employee=employee,
			from_date=from_date,
			to_date=to_date,
		)
		return success(data=data or [])
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def apply(leave_type, from_date, to_date, half_day=0, half_day_date=None,
		description=None, follow_via_email=1):
	employee = get_current_employee()
	if not leave_type or not from_date or not to_date:
		return error("leave_type, from_date and to_date are required.", http_status_code=400)

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"half_day": int(half_day),
				"half_day_date": half_day_date,
				"description": description,
				"follow_via_email": int(follow_via_email),
				"status": "Open",
			}
		)
		doc.insert()
		frappe.db.commit()
		return success(data={"name": doc.name, "status": doc.status})
	except frappe.ValidationError as e:
		return error(str(e), "VALIDATION_ERROR", http_status_code=422)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def approve(name, action, comment=None):
	"""Approve or Reject a Leave Application (for leave approvers)."""
	if action not in ("Approve", "Reject"):
		return error("action must be 'Approve' or 'Reject'.", http_status_code=400)

	doc = frappe.get_doc("Leave Application", name)
	if not frappe.has_permission("Leave Application", "write", doc=doc):
		return error("Not permitted.", http_status_code=403)

	doc.status = "Approved" if action == "Approve" else "Rejected"
	if comment:
		doc.add_comment("Comment", comment)
	doc.save()
	frappe.db.commit()
	return success(data={"name": name, "status": doc.status})
