import frappe
from frappe.model.document import Document


class HRMSMobileSettings(Document):
	# No jwt_secret here by design — auth_service derives the JWT signing key from the
	# site's encryption key, so there is no secret to seed, store or rotate.

	def on_update(self):
		frappe.cache.delete_key("hrms_mobile_settings")
