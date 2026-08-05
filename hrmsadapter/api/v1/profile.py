"""Profile API — v1"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.services.permission_service import PermissionService
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_my_profile():
	user = frappe.session.user
	employee_name = frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, "name"
	)

	employee = {}
	if employee_name:
		employee = frappe.db.get_value(
			"Employee",
			employee_name,
			[
				"name", "employee_name", "image", "department", "designation",
				"company", "date_of_joining", "gender", "date_of_birth",
				"cell_number", "personal_email", "company_email",
				"reports_to", "branch", "grade", "employment_type",
				"notice_applicable", "relieving_date",
			],
			as_dict=True,
		) or {}

	user_doc = frappe.db.get_value(
		"User", user,
		["full_name", "email", "user_image", "language", "time_zone"],
		as_dict=True,
	) or {}

	permissions = PermissionService.get_user_module_access(user)

	return success(
		data={
			"user": user_doc,
			"employee": employee,
			"permissions": permissions,
		}
	)


@frappe.whitelist(methods=["PUT"])
@require_mobile_auth
def update_profile_image(image_base64, filename):
	"""Upload a new profile image for the current user."""
	if not image_base64 or not filename:
		return error("image_base64 and filename are required.", http_status_code=400)

	user = frappe.session.user
	try:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"content": image_base64,
				"decode": True,
				"is_private": 0,
				"attached_to_doctype": "User",
				"attached_to_name": user,
			}
		)
		file_doc.insert(ignore_permissions=True)
		frappe.db.set_value("User", user, "user_image", file_doc.file_url)
		return success(data={"file_url": file_doc.file_url})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_permissions():
	"""Return the module access matrix for the current user."""
	return success(data=PermissionService.get_user_module_access())
