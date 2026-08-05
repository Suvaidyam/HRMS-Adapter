"""
Settings & Branding API — v1

get_branding is guest-accessible so Flutter can brand its login screen
before the user authenticates.
"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import success


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_branding():
	"""Return app branding info. No auth required — used on login screen."""
	s = frappe.get_cached_doc("HRMS Mobile Settings")

	company = s.company_override or frappe.db.get_default("company")
	company_doc = frappe.get_cached_doc("Company", company) if company else None

	return success(
		data={
			"app_name": s.app_name or "HRMS",
			"company": company,
			"company_full_name": company_doc.company_name if company_doc else company,
			"logo_light": s.logo_light,
			"logo_dark": s.logo_dark,
			"splash_image": s.splash_image,
			"primary_color": s.primary_color,
			"secondary_color": s.secondary_color,
			"app_version": s.app_version,
			"min_supported_version": s.min_supported_version,
			"force_update_below": s.force_update_below,
			"store_urls": {
				"ios": s.app_store_url_ios,
				"android": s.app_store_url_android,
			},
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
