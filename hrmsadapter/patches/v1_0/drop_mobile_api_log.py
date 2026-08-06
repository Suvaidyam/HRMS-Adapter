"""Remove the Mobile API Log DocType and its data.

Request auditing was dropped, so the after_request writer, the retention job and
the DocType are all gone from the codebase. Deleting the DocType record does not
drop `tabMobile API Log` (see frappe.model.delete_doc.delete_from_table), so the
table is dropped explicitly here — otherwise every existing site keeps an orphan
table of log rows that nothing will ever purge.

Idempotent — safe to re-run.
"""
import frappe


def execute():
	if frappe.db.exists("DocType", "Mobile API Log"):
		frappe.delete_doc("DocType", "Mobile API Log", force=True, ignore_missing=True)

	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabMobile API Log`")
	frappe.db.commit()
