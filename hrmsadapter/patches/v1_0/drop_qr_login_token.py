"""Remove the QR Login Token DocType and its data.

Two QR flows existed side by side. The one that ships is Redis-backed —
`QR_code_generator.generate_qr_code` parks the claim under
`hrms_mobile_token:{token}` and `auth.validate_qr_token` redeems it — and it
never touched this DocType. The DocType-backed desktop handshake
(generate/scan/consume/poll) had no client on either end, so it is gone along
with its endpoints, service functions and hourly expiry job.

Deleting the DocType record does not drop `tabQR Login Token`
(see frappe.model.delete_doc.delete_from_table), so the table is dropped
explicitly — otherwise every existing site keeps an orphan table of short-lived
tokens that nothing will ever purge.

Idempotent — safe to re-run.
"""
import frappe


def execute():
	if frappe.db.exists("DocType", "QR Login Token"):
		frappe.delete_doc("DocType", "QR Login Token", force=True, ignore_missing=True)

	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabQR Login Token`")
	frappe.db.commit()
