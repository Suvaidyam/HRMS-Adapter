import frappe
from frappe.model.document import Document


class MobileFieldMapping(Document):
	def validate(self):
		if not self.mobile_key:
			self.mobile_key = self.fieldname

		existing = frappe.db.get_value(
			"Mobile Field Mapping",
			{"doctype_name": self.doctype_name, "fieldname": self.fieldname},
			"name",
		)
		if existing and existing != self.name:
			frappe.throw(
				f"A mapping for {self.doctype_name}.{self.fieldname} already exists.",
				frappe.DuplicateEntryError,
			)

	def on_update(self):
		frappe.cache.delete_key(f"mobile_field_mapping:{self.doctype_name}")
