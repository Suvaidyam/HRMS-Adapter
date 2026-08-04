"""
PermissionService — computes module-level access for a user.

Combines HRMS Mobile Settings feature flags with Frappe role-based
permissions. Flutter never makes its own permission decisions.
"""
import frappe


MODULE_DOCTYPE_MAP = {
	"leave": "Leave Application",
	"expense": "Expense Claim",
	"attendance": "Attendance",
	"payroll": "Salary Slip",
	"shift": "Shift Request",
	"travel": "Travel Request",
	"loan": "Loan Application",
	"appraisal": "Appraisal",
}

APPROVER_ROLE_MAP = {
	"Leave Application": "Leave Approver",
	"Expense Claim": "Expense Approver",
	"Shift Request": "HR Manager",
}


class PermissionService:
	@classmethod
	def get_user_module_access(cls, user: str = None) -> dict:
		user = user or frappe.session.user
		settings = frappe.get_cached_doc("HRMS Mobile Settings")

		feature_map = {
			"leave": settings.enable_leave,
			"expense": settings.enable_expense,
			"attendance": settings.enable_attendance,
			"payroll": settings.enable_payroll,
			"shift": 1,
			"travel": 1,
			"loan": 1,
			"appraisal": 1,
		}

		access = {}
		for module, doctype in MODULE_DOCTYPE_MAP.items():
			if not feature_map.get(module, 1):
				access[module] = {"enabled": False}
				continue

			try:
				can_read = frappe.has_permission(doctype, "read", user=user)
				can_create = frappe.has_permission(doctype, "create", user=user)
				can_submit = frappe.has_permission(doctype, "submit", user=user)
				can_approve = cls.can_approve(user, doctype)
			except Exception:
				can_read = can_create = can_submit = can_approve = False

			access[module] = {
				"enabled": True,
				"read": can_read,
				"create": can_create,
				"submit": can_submit,
				"approve": can_approve,
			}

		access["approvals"] = {
			"enabled": bool(settings.enable_approvals),
			"read": True,
		}

		return access

	@classmethod
	def get_permitted_modules(cls, user: str = None) -> list:
		access = cls.get_user_module_access(user)
		return [m for m, perms in access.items() if perms.get("enabled") and perms.get("read")]

	@classmethod
	def can_approve(cls, user: str, doctype: str) -> bool:
		role = APPROVER_ROLE_MAP.get(doctype)
		if role:
			user_roles = frappe.get_roles(user)
			return role in user_roles or "HR Manager" in user_roles
		return False
