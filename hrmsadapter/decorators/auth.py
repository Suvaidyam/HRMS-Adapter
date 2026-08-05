"""
Mobile JWT authentication decorator and before_request hook.

Priority order for authentication:
  1. Authorization: Bearer <jwt>  (preferred for mobile)
  2. Authorization: Token <api_key>:<api_secret>  (Frappe native, for tooling)
  3. Session cookie (Frappe native, web fallback)
"""
from functools import wraps

import frappe


def require_mobile_auth(fn):
	"""
	Decorator for v1 API endpoints that require a valid mobile session.
	Validates Bearer JWT if present; falls back to Frappe session.
	"""

	@wraps(fn)
	def wrapper(*args, **kwargs):
		_authenticate_request()
		if frappe.session.user == "Guest":
			frappe.throw("Authentication required.", frappe.AuthenticationError)
		return fn(*args, **kwargs)

	return wrapper


def validate_mobile_jwt_if_present():
	"""
	before_request hook.
	Activates only when an Authorization: Bearer header is present.
	Transparent to all non-mobile / non-JWT requests.
	"""
	try:
		auth_header = frappe.get_request_header("Authorization", "")
		if auth_header.startswith("Bearer "):
			_authenticate_bearer(auth_header[7:])
	except frappe.AuthenticationError:
		raise
	except Exception:
		pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _authenticate_request():
	auth_header = frappe.get_request_header("Authorization", "")
	if auth_header.startswith("Bearer "):
		_authenticate_bearer(auth_header[7:])


def _authenticate_bearer(token: str):
	from hrmsadapter.services import auth_service

	claims = auth_service.validate_token(token)
	frappe.set_user(claims["sub"])
	frappe.local.mobile_device_id = claims.get("device_id")
	frappe.local.mobile_jwt_claims = claims
