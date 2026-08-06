"""One-time normalisation for the Mobile Device session/blocking change.

Idempotent — safe to re-run.
"""
import frappe


def execute():
	if not frappe.db.table_exists("Mobile Device"):
		return

	frappe.reload_doctype("Mobile Device")

	_migrate_refresh_token_hash()
	_backfill_liveness()
	_backfill_ownership()
	_report_owner_mismatches()
	_ensure_device_limit_default()

	frappe.db.commit()


def _migrate_refresh_token_hash():
	"""refresh_token_hash was a Password field, so the real value lives in `__Auth`
	while the column holds asterisks.

	Copy it back into the column rather than wiping it, so live refresh tokens keep
	working and nobody is forced to log in again. After this, clearing the column
	really invalidates the token — as a Password field it did not, because
	get_password() fell back to the surviving `__Auth` row.
	"""
	from frappe.utils.password import get_decrypted_password

	for row in frappe.get_all("Mobile Device", fields=["name", "refresh_token_hash"]):
		column = row.refresh_token_hash or ""
		if column and set(column) != {"*"}:
			# Already the real hash (written by refresh rotation via db.set_value).
			continue

		real = get_decrypted_password(
			"Mobile Device", row.name, "refresh_token_hash", raise_exception=False
		)
		frappe.db.set_value(
			"Mobile Device", row.name, "refresh_token_hash", real or "", update_modified=False
		)

	frappe.db.delete("__Auth", {"doctype": "Mobile Device", "fieldname": "refresh_token_hash"})


def _backfill_liveness():
	"""last_active was only ever written by device.register, so most rows are NULL.

	The nightly sweep now falls back through last_login, but seed the column so the
	device list and the desk show something truthful.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabMobile Device`
		SET last_active = COALESCE(last_login, modified, creation)
		WHERE last_active IS NULL
		"""
	)


def _backfill_ownership():
	"""`user` is the authorisation subject for every query in this app and is
	mandatory again. Rows created while it was optional may have it empty."""
	frappe.db.sql(
		"""
		UPDATE `tabMobile Device` md
		INNER JOIN `tabEmployee` e ON e.name = md.employee
		SET md.user = e.user_id
		WHERE IFNULL(md.user, '') = '' AND IFNULL(e.user_id, '') != ''
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabMobile Device` md
		INNER JOIN `tabEmployee` e ON e.user_id = md.user AND e.status = 'Active'
		SET md.employee = e.name
		WHERE IFNULL(md.employee, '') = ''
		"""
	)


def _report_owner_mismatches():
	"""Rows whose `user` may have been rewritten by the short-lived
	`fetch_from: employee.user_id` on the user field.

	Reported for manual review, not repaired automatically — `user` is authoritative
	and we cannot tell from here which of the two values was intended.
	"""
	suspect = frappe.db.sql(
		"""
		SELECT md.name, md.device_id, md.user, md.employee, e.user_id AS employee_user
		FROM `tabMobile Device` md
		INNER JOIN `tabEmployee` e ON e.name = md.employee
		WHERE IFNULL(md.user, '') != '' AND IFNULL(e.user_id, '') != '' AND e.user_id != md.user
		""",
		as_dict=True,
	)
	if suspect:
		frappe.log_error(
			frappe.as_json(suspect),
			"hrmsadapter: Mobile Device rows with user/employee mismatch — review",
		)


def _ensure_device_limit_default():
	"""create_default_settings early-returns for an existing singleton, so it never
	backfills. The device limit must not be 0/NULL."""
	if not frappe.db.get_single_value("HRMS Mobile Settings", "max_devices_per_user"):
		frappe.db.set_single_value("HRMS Mobile Settings", "max_devices_per_user", 5)
