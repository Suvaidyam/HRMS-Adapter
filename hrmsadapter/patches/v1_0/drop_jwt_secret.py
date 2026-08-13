"""Remove the stored JWT secret.

auth_service now derives the HS256 signing key from the site's encryption key, so
nothing has to be persisted. The `jwt_secret` field is gone from HRMS Mobile
Settings, but dropping a Password field leaves its ciphertext behind in `__Auth`
(and a masked placeholder in `tabSingles`), so both are cleared here — a secret we
no longer read should not keep sitting in the database.

Idempotent — safe to re-run.
"""
import frappe


def execute():
	frappe.db.delete(
		"__Auth",
		{"doctype": "HRMS Mobile Settings", "fieldname": "jwt_secret"},
	)
	frappe.db.delete(
		"Singles",
		{"doctype": "HRMS Mobile Settings", "field": "jwt_secret"},
	)
	frappe.clear_cache(doctype="HRMS Mobile Settings")
	frappe.db.commit()
