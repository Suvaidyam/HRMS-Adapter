"""
Approval Center API — v1

Generic pending approvals across all HRMS modules.
Flutter never knows workflow internals.
"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import clamp_pagination


APPROVAL_DOCTYPES = [
	{
		"doctype": "Leave Application",
		"approver_field": "leave_approver",
		"status_field": "status",
		"pending_values": ["Open"],
		"fields": ["name", "employee", "employee_name", "leave_type",
				   "from_date", "to_date", "total_leave_days", "status"],
	},
	{
		"doctype": "Expense Claim",
		"approver_field": "expense_approver",
		"status_field": "approval_status",
		"pending_values": ["Draft", "Submitted"],
		"fields": ["name", "employee", "employee_name", "posting_date",
				   "total_claimed_amount", "approval_status", "currency"],
	},
	{
		"doctype": "Shift Request",
		"approver_field": "approver",
		"status_field": "status",
		"pending_values": ["Draft"],
		"fields": ["name", "employee", "employee_name", "shift_type",
				   "from_date", "to_date", "status"],
	},
	{
		"doctype": "Attendance Request",
		"approver_field": None,
		"status_field": "status",
		"pending_values": ["Draft"],
		"fields": ["name", "employee", "employee_name", "from_date", "to_date", "reason", "status"],
	},
]


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_pending_approvals(doctype=None, limit=20, offset=0):
	limit, offset = clamp_pagination(limit, offset)
	user = frappe.session.user
	all_items = []

	configs = [c for c in APPROVAL_DOCTYPES if not doctype or c["doctype"] == doctype]

	for config in configs:
		if not frappe.has_permission(config["doctype"], "read"):
			continue

		filters = {config["status_field"]: ("in", config["pending_values"])}
		if config["approver_field"]:
			filters[config["approver_field"]] = user

		try:
			rows = frappe.get_all(
				config["doctype"],
				filters=filters,
				fields=config["fields"],
				order_by="modified desc",
				limit=200,
			)
			for row in rows:
				row["_doctype"] = config["doctype"]
			all_items.extend(rows)
		except Exception:
			pass

	total = len(all_items)
	page_items = all_items[offset: offset + limit]
	return success(data={"items": page_items, "total": total, "limit": limit, "offset": offset})


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def take_action(doctype, name, action, comment=None):
	"""
	Apply an approval action (Approve/Reject/etc.) on any supported doctype.
	Applies workflow transition if a workflow exists; falls back to status update.
	"""
	if not frappe.has_permission(doctype, "write"):
		return error("Not permitted.", http_status_code=403)

	doc = frappe.get_doc(doctype, name)

	# Try workflow transition first
	workflow = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
	if workflow:
		try:
			frappe.model.workflow.apply_workflow(doc, action)
			if comment:
				doc.add_comment("Comment", comment)
			doc.save()
			frappe.db.commit()
			return success(data={"name": name, "status": doc.get("status") or doc.get("approval_status")})
		except Exception as e:
			return error(str(e), http_status_code=422)

	# Fallback: direct status update for Leave Application
	if doctype == "Leave Application":
		doc.status = "Approved" if action == "Approve" else "Rejected"
		if comment:
			doc.add_comment("Comment", comment)
		doc.save()
		frappe.db.commit()
		return success(data={"name": name, "status": doc.status})

	return error(f"No workflow or direct action handler for {doctype}.", http_status_code=400)
