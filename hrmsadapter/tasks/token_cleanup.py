"""
Scheduled cleanup tasks for tokens and devices.
"""
import frappe
from frappe.utils import add_to_date, now_datetime


def cleanup_blacklisted_tokens():
	"""Redis TTL handles JWT blacklist expiry automatically; this is a no-op placeholder."""
	pass


def expire_inactive_devices():
	"""Mark Mobile Devices with no activity in 90 days as Expired.

	Falls back through last_login/modified/creation because last_active is only
	written by the activity touch, register and refresh. The old
	`OR last_active IS NULL` clause expired every freshly-logged-in device on the
	next nightly run, which wiped its FCM token and silently killed the user's push
	notifications and refresh flow.

	Goes through deactivate_device rather than a bulk UPDATE so the credentials are
	cleared and the request-time state cache is invalidated.
	"""
	from hrmsadapter.services import auth_service

	cutoff = add_to_date(now_datetime(), days=-90)
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabMobile Device`
		WHERE status = 'Active'
		  AND COALESCE(last_active, last_login, modified, creation) < %s
		""",
		(cutoff,),
		as_dict=True,
	)

	for row in rows:
		try:
			auth_service.deactivate_device(row.name, "Expired", "Inactivity")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "hrmsadapter: expire_inactive_devices")

	frappe.db.commit()
