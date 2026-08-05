import frappe


def require_params(*param_names):
	"""Raise ValidationError if any of the named params are missing or empty."""
	missing = [p for p in param_names if not frappe.form_dict.get(p)]
	if missing:
		frappe.throw(
			f"Missing required parameter(s): {', '.join(missing)}",
			frappe.ValidationError,
		)


def get_current_employee(user=None):
	"""Return the Employee linked to the current (or given) user. Throws if none."""
	user = user or frappe.session.user
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not employee:
		frappe.throw(
			"No active Employee record found for the current user.",
			frappe.DoesNotExistError,
		)
	return employee


def validate_date_range(from_date, to_date):
	from frappe.utils import getdate

	if getdate(from_date) > getdate(to_date):
		frappe.throw("from_date cannot be after to_date.", frappe.ValidationError)


def clamp_pagination(limit, offset, max_limit=200):
	try:
		limit = min(int(limit or 20), max_limit)
		offset = max(int(offset or 0), 0)
	except (TypeError, ValueError):
		limit, offset = 20, 0
	return limit, offset
