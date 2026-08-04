"""
Scheduled cleanup tasks for tokens, devices, and API logs.
"""
import frappe
from frappe.utils import add_to_date, now_datetime


def expire_qr_tokens():
	"""Mark all QR Login Tokens past their expiry as Expired."""
	frappe.db.sql(
		"""
		UPDATE `tabQR Login Token`
		SET status = 'Expired'
		WHERE status IN ('Pending', 'Scanned')
		  AND expiry < %s
		""",
		(now_datetime(),),
	)
	frappe.db.commit()


def cleanup_blacklisted_tokens():
	"""Redis TTL handles JWT blacklist expiry automatically; this is a no-op placeholder."""
	pass


def purge_old_api_logs():
	"""Delete Mobile API Log records older than retention period (default 30 days)."""
	if not frappe.db.table_exists("tabMobile API Log"):
		return

	retention_days = 30
	cutoff = add_to_date(now_datetime(), days=-retention_days)
	frappe.db.delete("Mobile API Log", {"creation": ("<", cutoff)})
	frappe.db.commit()


def expire_inactive_devices():
	"""Mark Mobile Devices with no activity in 90 days as Expired."""
	cutoff = add_to_date(now_datetime(), days=-90)
	frappe.db.sql(
		"""
		UPDATE `tabMobile Device`
		SET status = 'Expired'
		WHERE status = 'Active'
		  AND (last_active < %s OR last_active IS NULL)
		""",
		(cutoff,),
	)
	frappe.db.commit()
