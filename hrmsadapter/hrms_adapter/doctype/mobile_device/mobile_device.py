import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class MobileDevice(Document):
	def before_insert(self):
		if not self.employee and self.user:
			self.employee = frappe.db.get_value(
				"Employee", {"user_id": self.user, "status": "Active"}, "name"
			)

	def on_update(self):
		if self.status in ("Revoked", "Expired"):
			self._clear_tokens()

	def _clear_tokens(self):
		frappe.db.set_value(
			"Mobile Device",
			self.name,
			{"refresh_token_hash": "", "fcm_token": ""},
			update_modified=False,
		)

	def touch(self, ip=None):
		update = {"last_active": now_datetime()}
		if ip:
			update["last_ip"] = ip
		frappe.db.set_value("Mobile Device", self.name, update, update_modified=False)
