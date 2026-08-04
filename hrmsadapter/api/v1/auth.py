"""
Authentication API — v1

All endpoints are Frappe whitelisted methods.
URL pattern: /api/method/hrmsadapter.api.v1.auth.<function>
"""
import frappe
from frappe.utils import now_datetime

from hrmsadapter.services import auth_service
from hrmsadapter.utils.response import error, success


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(usr, pwd, device_id, platform=None, device_name=None, os_version=None,
		app_version=None, device_model=None, device_brand=None, fcm_token=None):
	"""
	Authenticate with ERPNext credentials.
	Returns JWT access + refresh tokens alongside employee info.
	"""
	if not usr or not pwd:
		return error("usr and pwd are required.", "MISSING_PARAMS", http_status_code=400)
	if not device_id:
		return error("device_id is required.", "MISSING_PARAMS", http_status_code=400)

	# Delegate credential check to Frappe's login manager
	login_manager = frappe.auth.LoginManager()
	try:
		login_manager.authenticate(user=usr, pwd=pwd)
		login_manager.post_login()
	except frappe.AuthenticationError:
		frappe.clear_messages()
		return error("Invalid credentials.", "AUTH_FAILED", http_status_code=401)

	user = frappe.session.user

	# Generate token pair
	raw_refresh, refresh_hash = auth_service.generate_refresh_token()
	access_token = auth_service.generate_access_token(user, device_id)

	# Upsert device
	auth_service.upsert_device(
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

	employee = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["name", "employee_name", "image", "department", "designation", "company"],
		as_dict=True,
	)

	settings = frappe.get_cached_doc("HRMS Mobile Settings")

	_invoke_hooks("after_mobile_login", user=user, device_id=device_id)

	return success(
		data={
			"access_token": access_token,
			"refresh_token": raw_refresh,
			"expires_in": (settings.jwt_expiry_hours or 24) * 3600,
			"user": {
				"email": user,
				"full_name": frappe.db.get_value("User", user, "full_name"),
				"user_image": frappe.db.get_value("User", user, "user_image"),
			},
			"employee": employee or {},
		}
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def refresh_token(refresh_token, device_id):
	"""Exchange a valid refresh token for a new access token."""
	if not refresh_token or not device_id:
		return error("refresh_token and device_id are required.", http_status_code=400)

	device_name = frappe.db.get_value(
		"Mobile Device",
		{"device_id": device_id, "status": "Active"},
		"name",
	)
	if not device_name:
		return error("Device not found or revoked.", "DEVICE_NOT_FOUND", http_status_code=401)

	device = frappe.get_doc("Mobile Device", device_name)

	if not auth_service.verify_refresh_token(device, refresh_token):
		return error("Invalid refresh token.", "INVALID_REFRESH_TOKEN", http_status_code=401)

	from frappe.utils import get_datetime
	if get_datetime(device.refresh_token_expiry) < get_datetime(now_datetime()):
		return error("Refresh token has expired.", "REFRESH_EXPIRED", http_status_code=401)

	settings = frappe.get_cached_doc("HRMS Mobile Settings")
	new_access_token = auth_service.generate_access_token(device.user, device_id)

	# Rotate refresh token if less than 7 days remain
	from frappe.utils import date_diff
	days_left = date_diff(device.refresh_token_expiry, now_datetime())
	new_raw_refresh = None
	if days_left < 7:
		new_raw_refresh, new_hash = auth_service.generate_refresh_token()
		from frappe.utils import add_to_date
		frappe.db.set_value(
			"Mobile Device",
			device_name,
			{
				"refresh_token_hash": new_hash,
				"refresh_token_expiry": add_to_date(
					now_datetime(), days=settings.refresh_token_expiry_days or 30
				),
			},
			update_modified=False,
		)

	response_data = {
		"access_token": new_access_token,
		"expires_in": (settings.jwt_expiry_hours or 24) * 3600,
	}
	if new_raw_refresh:
		response_data["refresh_token"] = new_raw_refresh

	return success(data=response_data)


@frappe.whitelist(methods=["POST"])
def logout(device_id=None):
	"""Revoke device and blacklist current JWT."""
	user = frappe.session.user
	claims = getattr(frappe.local, "mobile_jwt_claims", {})

	if claims.get("jti") and claims.get("exp"):
		auth_service.blacklist_token(claims["jti"], claims["exp"])

	if device_id:
		frappe.db.set_value(
			"Mobile Device",
			{"device_id": device_id, "user": user},
			"status",
			"Revoked",
		)
	else:
		frappe.db.set_value(
			"Mobile Device",
			{"user": user, "status": "Active"},
			"status",
			"Revoked",
		)

	frappe.db.commit()
	return success(data={"message": "Logged out successfully."})


# ---------------------------------------------------------------------------
# QR Login  (Phase 3 — implemented inline here for convenience)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["GET"])
def generate_qr_token():
	"""Desktop browser calls this to obtain a QR token to display."""
	ip = frappe.local.request_ip
	result = auth_service.create_qr_token(ip)
	return success(data=result)


@frappe.whitelist(methods=["POST"])
def scan_qr_token(qr_token, device_id):
	"""Mobile app (authenticated) scans and claims the QR token."""
	from hrmsadapter.decorators.auth import require_mobile_auth  # noqa: F401
	user = frappe.session.user
	if user == "Guest":
		return error("Authentication required.", http_status_code=401)
	auth_service.scan_qr_token(qr_token, user, device_id)
	return success(data={"status": "Scanned"})


@frappe.whitelist(allow_guest=True, methods=["GET"])
def poll_qr_status(qr_token):
	"""Desktop browser polls this until status is Consumed."""
	result = auth_service.poll_qr_status(qr_token)
	return success(data=result)


@frappe.whitelist(methods=["POST"])
def consume_qr_token(qr_token):
	"""Mobile app approves the login — generates JWT for desktop session."""
	user = frappe.session.user
	if user == "Guest":
		return error("Authentication required.", http_status_code=401)
	access_token = auth_service.consume_qr_token(qr_token)
	return success(data={"access_token": access_token, "status": "Consumed"})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _invoke_hooks(event: str, **kwargs):
	for hook in frappe.get_hooks(event):
		try:
			frappe.call(hook, **kwargs)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"hrmsadapter hook error: {event}")
