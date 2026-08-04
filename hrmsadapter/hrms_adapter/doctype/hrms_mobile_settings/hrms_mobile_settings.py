import frappe
from frappe.model.document import Document


class HRMSMobileSettings(Document):
	def validate(self):
		if not self.jwt_secret:
			self.jwt_secret = frappe.generate_hash(length=64)

	def on_update(self):
		frappe.cache.delete_key("hrms_mobile_settings")
