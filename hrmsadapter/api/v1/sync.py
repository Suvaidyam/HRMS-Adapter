"""Offline Sync API — v1"""
import json

import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.services import sync_service
from hrmsadapter.utils.response import error, success


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def full_sync(modules=None):
	"""Full data sync — returns complete snapshot for requested modules."""
	if isinstance(modules, str):
		try:
			modules = json.loads(modules)
		except Exception:
			modules = [m.strip() for m in modules.split(",") if m.strip()]
	if not modules:
		modules = ["leave", "attendance", "expense", "payroll", "profile"]

	user = frappe.session.user
	device_id = getattr(frappe.local, "mobile_device_id", "unknown")

	try:
		result = sync_service.full_sync(user, device_id, modules)
		return success(data=result)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def incremental_sync(sync_cursor=None, pending_uploads=None):
	"""Incremental sync — process offline uploads, return delta since cursor."""
	if isinstance(pending_uploads, str):
		try:
			pending_uploads = json.loads(pending_uploads)
		except Exception:
			pending_uploads = []

	user = frappe.session.user
	device_id = getattr(frappe.local, "mobile_device_id", "unknown")

	try:
		result = sync_service.incremental_sync(user, device_id, sync_cursor, pending_uploads or [])
		return success(data=result)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def upload_pending(records=None):
	"""Upload offline-created/modified records to the server."""
	if isinstance(records, str):
		try:
			records = json.loads(records)
		except Exception:
			return error("records must be a JSON array.", http_status_code=400)

	if not records:
		return error("records array is required.", http_status_code=400)

	user = frappe.session.user
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	results = [sync_service._upload_record(r, user, employee) for r in records]
	return success(data={"results": results})
