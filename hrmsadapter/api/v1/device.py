"""Device Management API — v1"""
import frappe
from frappe.utils import cint, now_datetime

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.services import auth_service
from hrmsadapter.utils.response import error, paginated, success
from hrmsadapter.utils.validators import clamp_pagination

BLOCKED_MESSAGE = "This device has been blocked. Contact your HR administrator."
DEVICE_ADMIN_ROLES = ["System Manager", "HR Manager"]


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def register(device_id, platform=None, device_name=None, os_version=None,
		app_version=None, device_model=None, device_brand=None, fcm_token=None):
	"""Refresh metadata for the current user's device, or enrol an unknown one.

	Deliberately never changes status and never touches the refresh token — that is
	login's job. A valid access token is not proof of credentials, so this endpoint
	must not be able to reactivate a device that was revoked out of band.
	"""
	if not device_id:
		return error("device_id is required.", "MISSING_PARAMS", http_status_code=400)

	user = frappe.session.user
	row = auth_service.get_device(device_id)

	if not row:
		result = auth_service.upsert_device(
			user=user,
			device_id=device_id,
			refresh_token_hash=None,
			platform=platform,
			device_name=device_name,
			os_version=os_version,
			app_version=app_version,
			device_model=device_model,
			device_brand=device_brand,
			fcm_token=fcm_token,
			ip=frappe.local.request_ip,
		)
		return success(
			data={"device_name": result["name"], "status": "Active", "action": result["action"]}
		)

	if row.status == "Blocked":
		return error(BLOCKED_MESSAGE, "DEVICE_BLOCKED", http_status_code=403)

	if row.user != user or row.status != "Active":
		return error(
			"Device session is no longer valid. Please log in again.",
			"DEVICE_NOT_ACTIVE",
			http_status_code=401,
		)

	update = {"last_active": now_datetime()}
	if app_version:
		update["app_version"] = app_version
	if device_name:
		update["device_name"] = device_name
	if fcm_token:
		update["fcm_token"] = fcm_token
		update["fcm_token_updated"] = now_datetime()

	frappe.db.set_value("Mobile Device", row.name, update, update_modified=False)
	frappe.db.commit()
	return success(data={"device_name": row.name, "status": "Active", "action": "updated"})


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def list_devices(include_inactive=0, limit=20, offset=0):
	"""Devices this user is logged in from, with the active count and the cap."""
	limit, offset = clamp_pagination(limit, offset)
	result = auth_service.get_user_devices(
		frappe.session.user,
		include_inactive=bool(cint(include_inactive)),
		limit=limit,
		offset=offset,
	)

	response = paginated(result["items"], result["total"], limit, offset)
	response["data"]["active_count"] = result["active_count"]
	response["data"]["max_devices"] = result["max_devices"]
	return response


@frappe.whitelist(methods=["PUT"])
@require_mobile_auth
def update_app_version(device_id, app_version):
	user = frappe.session.user
	doc_name = frappe.db.get_value(
		"Mobile Device", {"device_id": device_id, "user": user, "status": "Active"}, "name"
	)
	if not doc_name:
		return error("Device not found.", "DEVICE_NOT_FOUND", http_status_code=404)

	frappe.db.set_value("Mobile Device", doc_name, "app_version", app_version, update_modified=False)
	return success(data={"updated": True})


@frappe.whitelist(methods=["DELETE"])
@require_mobile_auth
def revoke(device_id):
	user = frappe.session.user
	row = auth_service.get_device(device_id)
	if not row or row.user != user:
		return error("Device not found.", "DEVICE_NOT_FOUND", http_status_code=404)
	if row.status == "Blocked":
		return error("This device is blocked and cannot be modified.", "DEVICE_BLOCKED",
			http_status_code=403)

	auth_service.deactivate_device(row.name, "Revoked", "Logout")

	# Revoking the device in hand also kills the token in hand. For any other device
	# we cannot know its jti — the request-time device check covers that instead.
	claims = getattr(frappe.local, "mobile_jwt_claims", {}) or {}
	if claims.get("device_id") == device_id and claims.get("jti") and claims.get("exp"):
		auth_service.blacklist_token(claims["jti"], claims["exp"])

	frappe.db.commit()
	return success(data={"revoked": True})


@frappe.whitelist(methods=["POST"])
def block(device_id, reason=None):
	"""Permanently block a device.

	There is no unblock endpoint: a blocked device is meant to stay blocked. A
	System Manager can still change it from the desk if it was done in error.
	"""
	frappe.only_for(DEVICE_ADMIN_ROLES)
	if not device_id:
		return error("device_id is required.", "MISSING_PARAMS", http_status_code=400)

	try:
		result = auth_service.block_device(device_id, reason)
	except frappe.DoesNotExistError:
		frappe.clear_messages()
		return error("Device not found.", "DEVICE_NOT_FOUND", http_status_code=404)

	return success(data=result, message="Device blocked permanently.")
