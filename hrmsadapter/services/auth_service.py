"""
AuthService — JWT generation/validation, QR token lifecycle,
refresh token rotation, and device upsert.

Uses PyJWT (bundled with Frappe v15).
JWT payload: { sub, device_id, jti, iat, exp }
Redis blacklist key: mobile_jwt_blacklist:{jti}
"""
import hashlib
import uuid
from datetime import datetime, timezone

import frappe
import jwt
from frappe.utils import add_to_date, get_datetime, now_datetime


def _get_settings():
	return frappe.get_cached_doc("HRMS Mobile Settings")


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------

def generate_access_token(user: str, device_id: str) -> str:
	settings = _get_settings()
	secret = settings.get_password("jwt_secret")
	now = datetime.now(timezone.utc)
	expiry_hours = settings.jwt_expiry_hours or 24

	payload = {
		"sub": user,
		"device_id": device_id,
		"jti": str(uuid.uuid4()),
		"iat": int(now.timestamp()),
		"exp": int(add_to_date(now, hours=expiry_hours).timestamp()),
	}
	return jwt.encode(payload, secret, algorithm="HS256")


def validate_token(token: str) -> dict:
	settings = _get_settings()
	secret = settings.get_password("jwt_secret")

	try:
		claims = jwt.decode(token, secret, algorithms=["HS256"])
	except jwt.ExpiredSignatureError:
		frappe.throw("Token has expired.", frappe.AuthenticationError)
	except jwt.InvalidTokenError as e:
		frappe.throw(f"Invalid token: {e}", frappe.AuthenticationError)

	jti = claims.get("jti", "")
	if jti and frappe.cache.get(f"mobile_jwt_blacklist:{jti}"):
		frappe.throw("Token has been revoked.", frappe.AuthenticationError)

	return claims


def blacklist_token(jti: str, exp: int):
	ttl = max(exp - int(datetime.now(timezone.utc).timestamp()), 1)
	frappe.cache.setex(f"mobile_jwt_blacklist:{jti}", ttl, "1")


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------

def generate_refresh_token() -> tuple:
	"""Returns (raw_token, sha256_hash)."""
	raw = frappe.generate_hash(length=48)
	hashed = hashlib.sha256(raw.encode()).hexdigest()
	return raw, hashed


def verify_refresh_token(device: "frappe.Document", raw_token: str) -> bool:
	stored_hash = device.get_password("refresh_token_hash")
	if not stored_hash:
		return False
	provided_hash = hashlib.sha256(raw_token.encode()).hexdigest()
	return stored_hash == provided_hash


# ---------------------------------------------------------------------------
# Device management
# ---------------------------------------------------------------------------

def upsert_device(
	user: str,
	device_id: str,
	refresh_token_hash: str,
	platform: str = None,
	device_name: str = None,
	os_version: str = None,
	app_version: str = None,
	device_model: str = None,
	device_brand: str = None,
	fcm_token: str = None,
	ip: str = None,
) -> str:
	"""Create or update a Mobile Device record. Returns the doc name."""
	settings = _get_settings()
	now = now_datetime()

	existing = frappe.db.get_value("Mobile Device", {"device_id": device_id}, "name")

	if existing:
		doc = frappe.get_doc("Mobile Device", existing)
		doc.user = user
		doc.status = "Active"
		doc.app_version = app_version or doc.app_version
		doc.last_login = now
		doc.last_ip = ip or doc.last_ip
		doc.refresh_token_hash = refresh_token_hash
		doc.refresh_token_expiry = add_to_date(
			now, days=settings.refresh_token_expiry_days or 30
		)
		if fcm_token:
			doc.fcm_token = fcm_token
			doc.fcm_token_updated = now
		doc.total_logins = (doc.total_logins or 0) + 1
		doc.save(ignore_permissions=True)
		return doc.name

	# Enforce max_devices_per_user
	max_devices = settings.max_devices_per_user or 5
	active_devices = frappe.get_all(
		"Mobile Device",
		filters={"user": user, "status": "Active"},
		fields=["name", "last_login"],
		order_by="last_login asc",
	)
	if len(active_devices) >= max_devices:
		oldest = active_devices[0]["name"]
		frappe.db.set_value("Mobile Device", oldest, "status", "Expired")

	doc = frappe.new_doc("Mobile Device")
	doc.user = user
	doc.device_id = device_id
	doc.status = "Active"
	doc.platform = platform
	doc.device_name = device_name
	doc.os_version = os_version
	doc.app_version = app_version
	doc.device_model = device_model
	doc.device_brand = device_brand
	doc.refresh_token_hash = refresh_token_hash
	doc.refresh_token_expiry = add_to_date(now, days=settings.refresh_token_expiry_days or 30)
	doc.last_login = now
	doc.registered_ip = ip
	doc.last_ip = ip
	doc.total_logins = 1
	if fcm_token:
		doc.fcm_token = fcm_token
		doc.fcm_token_updated = now
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
# QR Login lifecycle
# ---------------------------------------------------------------------------

def create_qr_token(ip: str) -> dict:
	settings = _get_settings()
	expiry_minutes = settings.qr_token_expiry_minutes or 5
	token = frappe.generate_hash(length=32)
	expiry = add_to_date(now_datetime(), minutes=expiry_minutes)

	doc = frappe.new_doc("QR Login Token")
	doc.token = token
	doc.status = "Pending"
	doc.expiry = expiry
	doc.generated_from_ip = ip
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"qr_token": token, "expires_at": str(expiry), "poll_interval_seconds": 3}


def scan_qr_token(token: str, user: str, device_id: str) -> None:
	doc = _get_valid_qr_token(token, expected_status="Pending")
	device_name = frappe.db.get_value("Mobile Device", {"device_id": device_id}, "name")
	doc.status = "Scanned"
	doc.claimed_by_user = user
	doc.claimed_device = device_name
	doc.claimed_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def consume_qr_token(token: str) -> str:
	"""Called by mobile after user approves. Returns a JWT for the desktop session."""
	doc = _get_valid_qr_token(token, expected_status="Scanned")
	access_token = generate_access_token(doc.claimed_by_user, "desktop-qr")
	doc.status = "Consumed"
	doc.session_data = access_token
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return access_token


def poll_qr_status(token: str) -> dict:
	doc = frappe.db.get_value(
		"QR Login Token",
		{"token": token},
		["status", "session_data", "expiry"],
		as_dict=True,
	)
	if not doc:
		return {"status": "Expired"}

	if get_datetime(doc.expiry) < get_datetime(now_datetime()):
		frappe.db.set_value("QR Login Token", {"token": token}, "status", "Expired")
		return {"status": "Expired"}

	result = {"status": doc.status}
	if doc.status == "Consumed":
		result["access_token"] = doc.session_data
	return result


# ---------------------------------------------------------------------------
# User disable hook
# ---------------------------------------------------------------------------

def on_user_update(doc, method=None):
	if doc.enabled == 0:
		frappe.db.set_value(
			"Mobile Device",
			{"user": doc.name, "status": "Active"},
			"status",
			"Revoked",
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_valid_qr_token(token: str, expected_status: str) -> "frappe.Document":
	name = frappe.db.get_value("QR Login Token", {"token": token}, "name")
	if not name:
		frappe.throw("Invalid QR token.", frappe.AuthenticationError)

	doc = frappe.get_doc("QR Login Token", name)

	if get_datetime(doc.expiry) < get_datetime(now_datetime()):
		doc.status = "Expired"
		doc.save(ignore_permissions=True)
		frappe.throw("QR token has expired.", frappe.AuthenticationError)

	if doc.status != expected_status:
		frappe.throw(
			f"QR token is in '{doc.status}' state, expected '{expected_status}'.",
			frappe.ValidationError,
		)
	return doc
