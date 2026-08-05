"""Device Management API — v1"""
import frappe
from frappe.utils import now_datetime

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.services import auth_service
from hrmsadapter.utils.response import error, success


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def register(device_id, platform=None, device_name=None, os_version=None,
		app_version=None, device_model=None, device_brand=None, fcm_token=None):
	"""Register or update a mobile device for the current user."""
	if not device_id:
		return error("device_id is required.", http_status_code=400)

	user = frappe.session.user
	existing = frappe.db.get_value(
		"Mobile Device",
		{"device_id": device_id, "user": user, "status": "Active"},
		["name", "refresh_token_hash"],
		as_dict=True,
	)

	if existing:
		update = {
			"last_active": now_datetime(),
			"app_version": app_version or "",
		}
		if fcm_token:
			update["fcm_token"] = fcm_token
			update["fcm_token_updated"] = now_datetime()
		frappe.db.set_value("Mobile Device", existing.name, update, update_modified=False)
		frappe.db.commit()
		return success(data={"device_name": existing.name, "status": "Active", "action": "updated"})

	# New device — needs a refresh token placeholder (will be set on login)
	_, refresh_hash = auth_service.generate_refresh_token()
	name = auth_service.upsert_device(
		user=user,
		device_id=device_id,
		refresh_token_hash=refresh_hash,
		platform=platform,
		device_name=device_name,
		os_version=os_version,
		app_version=app_version,
		device_model=device_model,
		device_brand=device_brand,
		fcm_token=fcm_token,
		ip=frappe.local.request_ip,
	)
	return success(data={"device_name": name, "status": "Active", "action": "created"})


@frappe.whitelist(methods=["PUT"])
@require_mobile_auth
def update_app_version(device_id, app_version):
	user = frappe.session.user
	doc_name = frappe.db.get_value(
		"Mobile Device", {"device_id": device_id, "user": user, "status": "Active"}, "name"
	)
	if not doc_name:
		return error("Device not found.", http_status_code=404)

	frappe.db.set_value("Mobile Device", doc_name, "app_version", app_version, update_modified=False)
	return success(data={"updated": True})


@frappe.whitelist(methods=["DELETE"])
@require_mobile_auth
def revoke(device_id):
	user = frappe.session.user
	doc_name = frappe.db.get_value(
		"Mobile Device", {"device_id": device_id, "user": user}, "name"
	)
	if not doc_name:
		return error("Device not found.", http_status_code=404)

	frappe.db.set_value(
		"Mobile Device", doc_name,
		{"status": "Revoked", "refresh_token_hash": "", "fcm_token": ""},
	)
	frappe.db.commit()
	return success(data={"revoked": True})
