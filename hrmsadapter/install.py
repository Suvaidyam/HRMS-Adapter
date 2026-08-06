import frappe


def after_install():
	_create_mobile_settings()
	_create_default_field_mappings()


def before_uninstall():
	frappe.db.delete("Mobile Device")
	frappe.db.delete("QR Login Token")
	frappe.db.delete("Mobile Notification")
	frappe.db.delete("Mobile Field Mapping")


def _create_mobile_settings():
	if frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings"):
		return

	settings = frappe.new_doc("HRMS Mobile Settings")
	settings.app_name = "HRMS"
	settings.jwt_expiry_hours = 24
	settings.refresh_token_expiry_days = 30
	settings.qr_token_expiry_minutes = 5
	settings.max_devices_per_user = 5
	settings.enable_attendance = 1
	settings.enable_leave = 1
	settings.enable_expense = 1
	settings.enable_payroll = 1
	settings.enable_approvals = 1
	settings.enable_announcements = 1
	settings.enable_qr_login = 1
	settings.enable_rate_limiting = 1
	settings.rate_limit_per_minute = 60
	settings.rate_limit_auth_per_minute = 10
	settings.jwt_secret = frappe.generate_hash(length=64)
	settings.insert(ignore_permissions=True)
	frappe.db.commit()


def _create_default_field_mappings():
	"""Seed sensible mobile_key aliases for common HRMS fields."""
	mappings = [
		# Leave Application
		("Leave Application", "employee", "employee_id"),
		("Leave Application", "leave_type", "leave_type"),
		("Leave Application", "from_date", "from_date"),
		("Leave Application", "to_date", "to_date"),
		("Leave Application", "total_leave_days", "days"),
		("Leave Application", "status", "status"),
		("Leave Application", "description", "reason"),
		# Expense Claim
		("Expense Claim", "employee", "employee_id"),
		("Expense Claim", "posting_date", "date"),
		("Expense Claim", "total_claimed_amount", "amount"),
		("Expense Claim", "approval_status", "status"),
		# Attendance
		("Attendance", "employee", "employee_id"),
		("Attendance", "attendance_date", "date"),
		("Attendance", "status", "status"),
		("Attendance", "in_time", "check_in"),
		("Attendance", "out_time", "check_out"),
	]

	for doctype, fieldname, mobile_key in mappings:
		if not frappe.db.exists("Mobile Field Mapping", {"doctype_name": doctype, "fieldname": fieldname}):
			doc = frappe.new_doc("Mobile Field Mapping")
			doc.doctype_name = doctype
			doc.fieldname = fieldname
			doc.mobile_key = mobile_key
			doc.is_active = 1
			doc.insert(ignore_permissions=True)

	if mappings:
		frappe.db.commit()
