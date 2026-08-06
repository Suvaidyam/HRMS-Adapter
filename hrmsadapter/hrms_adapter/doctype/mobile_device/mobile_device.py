import frappe
from frappe.model.document import Document


class MobileDevice(Document):
	def validate(self):
		if not self.employee and self.user:
			self.employee = frappe.db.get_value(
				"Employee", {"user_id": self.user, "status": "Active"}, "name"
			)

		self._guard_unblock()

	def _guard_unblock(self):
		"""Blocked is terminal.

		Defence in depth for desk edits and any future write path: the service layer
		already refuses to downgrade a Blocked row, but this also covers a direct
		save from the desk or /api/resource.
		"""
		previous = self.get_doc_before_save()
		if not previous or previous.status != "Blocked" or self.status == "Blocked":
			return

		if "System Manager" not in frappe.get_roles():
			frappe.throw(
				"Only a System Manager can unblock a device.",
				frappe.PermissionError,
			)

	def on_update(self):
		# Terminal statuses clear their own credentials in
		# auth_service.deactivate_device, which is the single writer. Here we only
		# keep the request-time state cache honest.
		from hrmsadapter.services.auth_service import invalidate_device_state_cache

		invalidate_device_state_cache(self.device_id)

	def on_trash(self):
		from hrmsadapter.services.auth_service import invalidate_device_state_cache

		invalidate_device_state_cache(self.device_id)
