"""
SyncService — full and incremental offline sync.

Sync cursor = ISO timestamp stored per (user, device_id) in Redis.
Full sync returns a complete snapshot. Incremental sync returns only
records modified after the stored cursor, plus soft-deleted records
from Frappe's Deleted Document log.
"""
import frappe
from frappe.utils import get_datetime, now_datetime


SYNC_DOCTYPES = {
	"leave": [
		{
			"doctype": "Leave Application",
			"employee_field": "employee",
			"fields": ["name", "leave_type", "from_date", "to_date", "total_leave_days",
					   "status", "description", "leave_approver", "modified"],
		},
		{
			"doctype": "Leave Type",
			"employee_field": None,
			"fields": ["name", "leave_type_name", "max_leaves_allowed", "modified"],
		},
	],
	"attendance": [
		{
			"doctype": "Attendance",
			"employee_field": "employee",
			"fields": ["name", "attendance_date", "status", "in_time", "out_time",
					   "working_hours", "modified"],
		},
	],
	"expense": [
		{
			"doctype": "Expense Claim",
			"employee_field": "employee",
			"fields": ["name", "posting_date", "total_claimed_amount",
					   "approval_status", "remarks", "modified"],
		},
		{
			"doctype": "Expense Claim Type",
			"employee_field": None,
			"fields": ["name", "description", "modified"],
		},
	],
	"payroll": [
		{
			"doctype": "Salary Slip",
			"employee_field": "employee",
			"fields": ["name", "posting_date", "start_date", "end_date",
					   "gross_pay", "net_pay", "total_deduction", "currency", "modified"],
		},
	],
	"profile": [
		{
			"doctype": "Employee",
			"employee_field": "name",
			"fields": ["name", "employee_name", "image", "department", "designation",
					   "company", "date_of_joining", "modified"],
			"self_only": True,
		},
	],
}


def _cursor_key(user: str, device_id: str) -> str:
	return f"hrmsadapter_sync_cursor:{user}:{device_id}"


def full_sync(user: str, device_id: str, modules: list) -> dict:
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	cursor = str(now_datetime())
	data = {}

	for module in modules:
		specs = SYNC_DOCTYPES.get(module, [])
		module_data = {}
		for spec in specs:
			rows = _fetch_records(spec, employee, since=None)
			module_data[spec["doctype"]] = rows
		data[module] = module_data

	frappe.cache.set_value(_cursor_key(user, device_id), cursor, expires_in_sec=86400 * 90)

	_invoke_hooks("after_mobile_sync", user=user, device_id=device_id, sync_type="full")
	return {"data": data, "sync_cursor": cursor, "deleted": {}}


def incremental_sync(user: str, device_id: str, cursor: str, pending_uploads: list) -> dict:
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")

	_invoke_hooks("before_mobile_sync", user=user, device_id=device_id, sync_type="incremental")

	conflicts = []
	upload_results = []
	for record in (pending_uploads or []):
		result = _upload_record(record, user, employee)
		upload_results.append(result)
		if result.get("status") == "conflict":
			conflicts.append(result)

	since = get_datetime(cursor) if cursor else None
	changes = {}
	for module, specs in SYNC_DOCTYPES.items():
		module_data = {}
		for spec in specs:
			rows = _fetch_records(spec, employee, since=since)
			if rows:
				module_data[spec["doctype"]] = rows
		if module_data:
			changes[module] = module_data

	deleted_ids = _get_deleted_records(since)
	new_cursor = str(now_datetime())
	frappe.cache.set_value(_cursor_key(user, device_id), new_cursor, expires_in_sec=86400 * 90)

	_invoke_hooks("after_mobile_sync", user=user, device_id=device_id, sync_type="incremental")
	return {
		"changes": changes,
		"conflicts": conflicts,
		"deleted_ids": deleted_ids,
		"new_cursor": new_cursor,
		"upload_results": upload_results,
	}


def _fetch_records(spec: dict, employee: str, since=None) -> list:
	filters = {}

	if spec.get("employee_field") and employee:
		if spec.get("self_only"):
			filters[spec["employee_field"]] = employee
		else:
			filters[spec["employee_field"]] = employee

	if since:
		filters["modified"] = (">", since)

	try:
		return frappe.get_all(
			spec["doctype"],
			filters=filters,
			fields=spec["fields"],
			order_by="modified asc",
			limit=500,
		)
	except Exception:
		return []


def _upload_record(record: dict, user: str, employee: str) -> dict:
	doctype = record.get("doctype")
	local_id = record.get("local_id")
	data = record.get("data", {})

	if not doctype or not data:
		return {"local_id": local_id, "status": "error", "error": "Missing doctype or data"}

	if not frappe.has_permission(doctype, "create"):
		return {"local_id": local_id, "status": "error", "error": "No permission"}

	try:
		server_name = data.get("name")
		if server_name and frappe.db.exists(doctype, server_name):
			server_doc = frappe.get_doc(doctype, server_name)
			if server_doc.docstatus != 0:
				return {
					"local_id": local_id,
					"status": "conflict",
					"server_name": server_name,
					"reason": "Document is submitted; server wins.",
				}
			server_modified = get_datetime(server_doc.modified)
			client_modified = get_datetime(data.get("modified", "2000-01-01"))
			if server_modified > client_modified:
				return {
					"local_id": local_id,
					"status": "conflict",
					"server_name": server_name,
					"reason": "Server version is newer.",
				}
			for k, v in data.items():
				if k not in ("name", "doctype", "docstatus", "modified", "creation"):
					setattr(server_doc, k, v)
			server_doc.save(ignore_permissions=True)
			frappe.db.commit()
			return {"local_id": local_id, "status": "updated", "server_name": server_doc.name}
		else:
			doc = frappe.get_doc({"doctype": doctype, **data})
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			return {"local_id": local_id, "status": "created", "server_name": doc.name}
	except Exception as e:
		return {"local_id": local_id, "status": "error", "error": str(e)}


def _get_deleted_records(since=None) -> dict:
	"""Return names of records deleted in Frappe's Deleted Document log."""
	filters = {}
	if since:
		filters["creation"] = (">", since)
	try:
		rows = frappe.get_all(
			"Deleted Document",
			filters=filters,
			fields=["deleted_doctype", "deleted_name"],
			limit=500,
		)
	except Exception:
		return {}

	result = {}
	for row in rows:
		result.setdefault(row.deleted_doctype, []).append(row.deleted_name)
	return result


def _invoke_hooks(event: str, **kwargs):
	for hook in frappe.get_hooks(event):
		try:
			frappe.call(hook, **kwargs)
		except Exception:
			pass
