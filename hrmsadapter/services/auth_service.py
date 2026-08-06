"""
AuthService — JWT generation/validation, QR token lifecycle,
refresh token rotation, and device upsert.

Uses PyJWT (bundled with Frappe v15).
JWT payload: { sub, device_id, jti, iat, exp }
Redis blacklist key: mobile_jwt_blacklist:{jti}
"""
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

import frappe
import jwt
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

# Reserved device id minted by consume_qr_token for desktop QR sessions. It has no
# Mobile Device row by design, so device-state checks must skip it.
QR_DESKTOP_DEVICE_ID = "desktop-qr"

# Device state is read on every authenticated request; cache it briefly. Every
# deliberate status write calls invalidate_device_state_cache(), so the TTL only
# bounds staleness for writers outside this module.
DEVICE_STATE_CACHE_TTL = 60

# At most one last_active write per device per this many seconds.
DEVICE_TOUCH_THROTTLE = 900


class DeviceBlockedError(frappe.AuthenticationError):
	"""A permanently blocked device attempted to authenticate.

	Subclasses AuthenticationError so an unwrapped throw still degrades to an auth
	failure, and carries its own status code (frappe.app reads http_status_code).
	"""

	http_status_code = 403


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
	"""Compare a raw refresh token against the stored hash.

	Reads the column directly: refresh_token_hash is a Data field, not a Password
	field. As a Password field the real value lived in `__Auth`, so blanking the
	column on revoke left get_password() returning the old hash — i.e. revocation
	silently did not invalidate the refresh token.
	"""
	stored_hash = device.refresh_token_hash or ""
	if not stored_hash or not raw_token:
		return False
	provided_hash = hashlib.sha256(raw_token.encode()).hexdigest()
	return hmac.compare_digest(stored_hash, provided_hash)


# ---------------------------------------------------------------------------
# Device management
# ---------------------------------------------------------------------------

def get_device(device_id: str) -> dict | None:
	"""THE device resolution rule.

	device_id is globally unique, so there is exactly one row per physical device
	regardless of owner or status. Deliberately unfiltered — callers decide what to
	do with a Revoked/Blocked row, so a blocked device can never hide behind a
	`status = "Active"` filter.
	"""
	if not device_id:
		return None
	return frappe.db.get_value(
		"Mobile Device",
		{"device_id": device_id},
		["name", "user", "status", "device_name"],
		as_dict=True,
	)


def get_device_state(device_id: str) -> dict | None:
	"""Briefly cached {name, user, status} for the request-time session check."""
	key = f"mobile_device_state:{device_id}"
	cached = frappe.cache.get_value(key)
	if cached is not None:
		return cached or None

	row = get_device(device_id)
	# `{}` is the "no such row" marker — distinct from a cache miss.
	frappe.cache.set_value(key, row or {}, expires_in_sec=DEVICE_STATE_CACHE_TTL)
	return row


def invalidate_device_state_cache(device_id: str) -> None:
	if device_id:
		frappe.cache.delete_value(f"mobile_device_state:{device_id}")


def is_device_blocked(device_id: str) -> bool:
	"""Login-time hard check. Reads the DB directly so cache staleness can never
	let a blocked device back in."""
	row = get_device(device_id)
	return bool(row and row.status == "Blocked")


def deactivate_device(name: str, status: str = "Revoked", reason: str | None = None) -> None:
	"""The single writer for every terminal device status.

	Uses doc.save() rather than frappe.db.set_value so the controller runs, and
	clears the credentials explicitly — every kill path in this app used to write
	the status only, leaving the refresh token and FCM token usable.
	"""
	doc = frappe.get_doc("Mobile Device", name)

	# Blocked is terminal: nothing here may downgrade it.
	if doc.status == "Blocked" and status != "Blocked":
		return

	doc.status = status
	doc.status_reason = reason
	doc.refresh_token_hash = ""
	doc.refresh_token_expiry = None
	doc.fcm_token = ""
	doc.fcm_token_updated = None
	doc.save(ignore_permissions=True)
	invalidate_device_state_cache(doc.device_id)


def block_device(device_id: str, reason: str | None = None) -> dict:
	"""Permanently block a device. There is no unblock API — see MobileDevice.validate."""
	row = get_device(device_id)
	if not row:
		frappe.throw(f"No device registered with id {device_id}.", frappe.DoesNotExistError)

	deactivate_device(row.name, "Blocked", "Admin Block")
	if reason:
		frappe.db.set_value(
			"Mobile Device", row.name, "device_name",
			f"{row.device_name or device_id} [BLOCKED: {reason[:60]}]",
			update_modified=False,
		)
	frappe.db.commit()
	return {"device_id": device_id, "name": row.name, "status": "Blocked"}


def assert_device_session_valid(claims: dict) -> None:
	"""Reject access tokens whose device row is no longer usable.

	Access tokens live for jwt_expiry_hours and validate_token() never touches the
	DB, so without this a revoked, expired, evicted or blocked device would keep
	full API access — including generic /api/resource/* — until natural expiry.

	Two deliberate escape hatches:
	  * the desktop QR session, which has no device row by design;
	  * a missing row (token minted before registration, or the row was hard
	    deleted by tests / before_uninstall). Blocking never deletes a row, so
	    failing open here cannot weaken the permanent block.
	"""
	device_id = claims.get("device_id")
	if not device_id or device_id == QR_DESKTOP_DEVICE_ID:
		return

	state = get_device_state(device_id)
	if not state:
		return

	if state["status"] != "Active":
		frappe.throw(
			"This device session is no longer active. Please log in again.",
			frappe.AuthenticationError,
		)
	if state["user"] != claims.get("sub"):
		# Reassigned device: the previous owner's still-live token dies here.
		frappe.throw("Token does not match this device.", frappe.AuthenticationError)

	mark_device_seen(state["name"], device_id, getattr(frappe.local, "request_ip", None))


def mark_device_seen(name: str, device_id: str, ip: str | None = None) -> None:
	"""Throttled last_active bump. Best-effort — must never fail a request.

	The write is deferred to an after_response callback because Frappe rolls the
	transaction back at the end of SAFE (GET) requests (frappe.app.sync_database),
	which would silently discard a mid-request write.
	"""
	key = f"mobile_device_touch:{device_id}"
	if frappe.cache.get_value(key):
		return
	# Set the flag before writing so a failing write cannot hot-loop.
	frappe.cache.set_value(key, 1, expires_in_sec=DEVICE_TOUCH_THROTTLE)

	def _write():
		try:
			update = {"last_active": now_datetime()}
			if ip:
				update["last_ip"] = ip
			frappe.db.set_value("Mobile Device", name, update, update_modified=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), "hrmsadapter: mark_device_seen")

	request = getattr(frappe.local, "request", None)
	if request is not None and hasattr(request, "after_response"):
		request.after_response.add(_write)
	else:
		_write()


def _enforce_device_limit(user: str, keep_device_name: str | None = None) -> list:
	"""Expire the oldest Active devices so that, counting the device being logged
	into, the user is at or under max_devices_per_user. Returns the evicted rows.

	for_update holds a row lock for the rest of the transaction so two concurrent
	logins cannot both pass the check (Mobile Device.user carries search_index, so
	the lock stays a per-user range instead of a table scan).
	"""
	max_devices = cint(_get_settings().max_devices_per_user) or 5

	rows = frappe.db.get_values(
		"Mobile Device",
		{"user": user, "status": "Active"},
		["name", "device_id", "device_name", "platform", "last_login", "creation"],
		order_by="creation asc",
		as_dict=True,
		for_update=True,
	) or []

	# Oldest-used first. Sorted here rather than in SQL because the query builder
	# splits order_by on commas, so an ifnull(a, b) expression would be mangled.
	# A never-logged-in row falls back to its creation time.
	rows.sort(key=lambda r: (r["last_login"] or r["creation"]))

	others = [r for r in rows if r["name"] != keep_device_name]
	excess = len(others) - max(max_devices - 1, 0)
	if excess <= 0:
		return []

	evicted = others[:excess]
	for row in evicted:
		deactivate_device(row["name"], "Expired", "Device Limit")

	return [
		{
			"device_id": r["device_id"],
			"device_name": r["device_name"],
			"platform": r["platform"],
		}
		for r in evicted
	]


def _resolve_employee(user: str) -> str | None:
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def upsert_device(
	user: str,
	device_id: str,
	refresh_token_hash: str | None = None,
	platform: str | None = None,
	device_name: str | None = None,
	os_version: str | None = None,
	app_version: str | None = None,
	device_model: str | None = None,
	device_brand: str | None = None,
	fcm_token: str | None = None,
	ip: str | None = None,
) -> dict:
	"""Create, update or reassign the Mobile Device row for device_id.

	Returns {name, action, evicted}. `refresh_token_hash=None` means "leave the
	stored refresh token alone" — device.register relies on that, since a valid
	access token is not proof of credentials.
	"""
	settings = _get_settings()
	now = now_datetime()
	existing = get_device(device_id)

	# Requirement: a blocked device can never log in again. Single rejection point.
	if existing and existing.status == "Blocked":
		frappe.throw(
			"This device has been blocked. Contact your HR administrator.",
			DeviceBlockedError,
		)

	if existing:
		doc = frappe.get_doc("Mobile Device", existing.name)
		reassigned = doc.user != user

		evicted = _enforce_device_limit(user, keep_device_name=doc.name)

		doc.user = user
		doc.status = "Active"
		doc.status_reason = None
		doc.platform = platform or doc.platform
		doc.device_name = device_name or doc.device_name
		doc.os_version = os_version or doc.os_version
		doc.app_version = app_version or doc.app_version
		doc.device_model = device_model or doc.device_model
		doc.device_brand = device_brand or doc.device_brand
		doc.last_login = now
		doc.last_active = now
		doc.last_ip = ip or doc.last_ip

		if reassigned:
			# Physical handover. The row survives because device_id identity is what
			# the permanent block hangs on, but nothing of the previous owner does.
			doc.employee = _resolve_employee(user)
			doc.total_logins = 1
			doc.fcm_token = ""
			doc.fcm_token_updated = None
			doc.registered_ip = ip
			doc.status_reason = "Reassigned"
			doc.refresh_token_hash = refresh_token_hash or ""
		else:
			doc.total_logins = cint(doc.total_logins) + 1
			if refresh_token_hash:
				doc.refresh_token_hash = refresh_token_hash

		if refresh_token_hash:
			doc.refresh_token_expiry = add_to_date(
				now, days=settings.refresh_token_expiry_days or 30
			)
		elif reassigned:
			doc.refresh_token_expiry = None

		if fcm_token:
			doc.fcm_token = fcm_token
			doc.fcm_token_updated = now

		doc.save(ignore_permissions=True)
		invalidate_device_state_cache(device_id)
		frappe.db.commit()
		return {
			"name": doc.name,
			"action": "reassigned" if reassigned else "updated",
			"evicted": evicted,
		}

	evicted = _enforce_device_limit(user, keep_device_name=None)

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
	if refresh_token_hash:
		doc.refresh_token_hash = refresh_token_hash
		doc.refresh_token_expiry = add_to_date(now, days=settings.refresh_token_expiry_days or 30)
	doc.last_login = now
	doc.last_active = now
	doc.registered_ip = ip
	doc.last_ip = ip
	doc.total_logins = 1
	if fcm_token:
		doc.fcm_token = fcm_token
		doc.fcm_token_updated = now
	doc.insert(ignore_permissions=True)
	invalidate_device_state_cache(device_id)
	frappe.db.commit()
	return {"name": doc.name, "action": "created", "evicted": evicted}


def get_user_devices(user: str, include_inactive: bool = False, limit: int = 20, offset: int = 0) -> dict:
	"""Device list for the mobile app. Never exposes fcm_token or refresh_token_hash."""
	filters = {"user": user}
	if not include_inactive:
		filters["status"] = "Active"

	items = frappe.get_all(
		"Mobile Device",
		filters=filters,
		fields=[
			"name", "device_id", "device_name", "platform", "os_version", "app_version",
			"device_model", "device_brand", "status", "status_reason", "last_login",
			"last_active", "total_logins", "fcm_token", "creation",
		],
		order_by="last_active desc, last_login desc, creation desc",
		limit=limit,
		start=offset,
	)

	current = getattr(frappe.local, "mobile_device_id", None)
	for row in items:
		row["is_current"] = 1 if current and row["device_id"] == current else 0
		row["push_enabled"] = 1 if row.pop("fcm_token", None) else 0

	return {
		"items": items,
		"total": frappe.db.count("Mobile Device", filters),
		"active_count": frappe.db.count("Mobile Device", {"user": user, "status": "Active"}),
		"max_devices": cint(_get_settings().max_devices_per_user) or 5,
	}


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
	# Only link a device the scanning user actually owns.
	row = get_device(device_id)
	device_name = row.name if row and row.user == user and row.status == "Active" else None
	doc.status = "Scanned"
	doc.claimed_by_user = user
	doc.claimed_device = device_name
	doc.claimed_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def consume_qr_token(token: str) -> str:
	"""Called by mobile after user approves. Returns a JWT for the desktop session."""
	doc = _get_valid_qr_token(token, expected_status="Scanned")
	access_token = generate_access_token(doc.claimed_by_user, QR_DESKTOP_DEVICE_ID)
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
		# Per row via deactivate_device so the credentials are really cleared — the
		# old bulk set_value left every refresh token usable.
		for name in frappe.get_all(
			"Mobile Device", filters={"user": doc.name, "status": "Active"}, pluck="name"
		):
			deactivate_device(name, "Revoked", "User Disabled")


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
