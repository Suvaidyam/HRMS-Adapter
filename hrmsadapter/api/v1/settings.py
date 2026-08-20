"""
Settings & Branding API — v1

get_branding is guest-accessible so Flutter can brand its login screen
before the user authenticates.
"""
import re

import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import success

#: Fallback brand colour when HRMS Mobile Settings has none set. Must stay in
#: sync with `AppColors.defaultPrimary` in the Flutter app.
DEFAULT_PRIMARY_COLOR = "#2E7D32"

_HEX_COLOR = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalize_color(value):
	"""Return `value` as `#RRGGBB`(`AA`), or None when it isn't a usable colour.

	The Color fieldtype normally stores `#RRGGBB`, but a value typed in by hand
	(or imported) can be bare hex, 3-digit shorthand, or junk. The mobile app
	must never be handed something it cannot parse, so anything unrecognised
	degrades to None and the client keeps its default.
	"""
	if not value:
		return None

	raw = str(value).strip()
	if not _HEX_COLOR.match(raw):
		return None

	hex_part = raw.lstrip("#")
	if len(hex_part) == 3:  # #abc → #aabbcc
		hex_part = "".join(ch * 2 for ch in hex_part)
	return f"#{hex_part.upper()}"


def _absolute_url(file_url):
	"""Turn a Frappe file path (`/files/x.png`) into a fully-qualified URL."""
	if not file_url:
		return None
	if file_url.startswith(("http://", "https://")):
		return file_url
	return frappe.utils.get_url(file_url)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_branding():
	"""Return app branding info. No auth required — used on login screen."""
	s = frappe.get_cached_doc("HRMS Mobile Settings")

	company = s.company_override or frappe.db.get_default("company")
	company_doc = frappe.get_cached_doc("Company", company) if company else None
	company_name = company_doc.company_name if company_doc else company

	return success(
		data={
			"app_name": s.app_name or "HRMS",
			"company": company,
			# `company_name` is the label the app shows; `company_full_name`
			# is kept for older clients that already read that key.
			"company_name": company_name,
			"company_full_name": company_name,
			# `logo_light` stays relative for backward compatibility; `logo_url`
			# is the absolute one the mobile app actually loads.
			"logo_light": s.logo_light,
			"logo_url": _absolute_url(s.logo_light),
			"primary_color": _normalize_color(s.primary_color) or DEFAULT_PRIMARY_COLOR,
			"store_urls": {
				"ios": s.app_store_url_ios,
				"android": s.app_store_url_android,
			},
			# The only feature flag served to guests. The QR button lives on the
			# login screen, which by definition runs before any JWT exists, so
			# get_feature_flags cannot reach it. Every other flag stays behind
			# auth — this one leaks nothing beyond "this site offers QR sign-in".
			"enable_qr_login": bool(s.enable_qr_login),
		}
	)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_feature_flags():
	"""Return enabled feature flags for the current session."""
	s = frappe.get_cached_doc("HRMS Mobile Settings")
	return success(
		data={
			"enable_attendance": bool(s.enable_attendance),
			"enable_leave": bool(s.enable_leave),
			"enable_expense": bool(s.enable_expense),
			"enable_payroll": bool(s.enable_payroll),
			"enable_approvals": bool(s.enable_approvals),
			"enable_checkin": bool(s.enable_checkin),
			"enable_offline_sync": bool(s.enable_offline_sync),
			"enable_announcements": bool(s.enable_announcements),
			"enable_worklog": bool(s.enable_worklog),
			"enable_travel": bool(s.enable_travel),
			"enable_qr_login": bool(s.enable_qr_login),
			"enable_push_notifications": bool(s.enable_push_notifications),
		}
	)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_app_config():
	"""Single endpoint returning branding + feature flags + HR settings."""
	branding = get_branding()
	flags = get_feature_flags()

	return success(
		data={
			"branding": branding.get("data", {}),
			"feature_flags": flags.get("data", {}),
		}
	)
