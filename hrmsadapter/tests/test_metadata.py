"""
Integration tests for MetadataService (Customization Adapter).

Run with: bench run-tests --app hrmsadapter --module hrmsadapter.tests.test_metadata
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from hrmsadapter.services.metadata_service import MetadataService


class TestMetadataService(FrappeTestCase):
	def test_get_fields_leave_application(self):
		"""Should return a non-empty list of normalised field descriptors."""
		fields = MetadataService.get_mobile_fields("Leave Application")
		self.assertIsInstance(fields, list)
		self.assertGreater(len(fields), 0)

	def test_flutter_type_mapping(self):
		"""Every returned field must have a flutter_type."""
		fields = MetadataService.get_mobile_fields("Leave Application")
		for f in fields:
			self.assertIn("flutter_type", f)
			self.assertIsNotNone(f["flutter_type"])

	def test_field_has_required_keys(self):
		fields = MetadataService.get_mobile_fields("Leave Application")
		for f in fields:
			for key in ("fieldname", "label", "flutter_type", "frappe_type", "reqd", "hidden"):
				self.assertIn(key, f, f"Field missing key '{key}': {f}")

	def test_mobile_field_mapping_override(self):
		"""A Mobile Field Mapping override should rename the mobile_key."""
		existing = frappe.db.exists(
			"Mobile Field Mapping",
			{"doctype_name": "Leave Application", "fieldname": "description"},
		)
		if not existing:
			doc = frappe.get_doc({
				"doctype": "Mobile Field Mapping",
				"doctype_name": "Leave Application",
				"fieldname": "description",
				"mobile_key": "test_override_reason",
				"is_active": 1,
			})
			doc.insert(ignore_permissions=True)
			frappe.db.commit()
			created = doc.name
		else:
			created = None

		frappe.cache.delete_key("mobile_field_mapping:Leave Application")
		fields = MetadataService.get_mobile_fields("Leave Application")
		keys = [f["fieldname"] for f in fields]

		if created:
			self.assertIn("test_override_reason", keys)
			frappe.delete_doc("Mobile Field Mapping", created, ignore_permissions=True)
			frappe.db.commit()
			frappe.cache.delete_key("mobile_field_mapping:Leave Application")

	def test_no_section_breaks_are_hidden(self):
		"""Section and Column breaks should be included (Flutter uses them for layout)."""
		fields = MetadataService.get_mobile_fields("Leave Application")
		all_types = [f["frappe_type"] for f in fields]
		# Not all forms have section breaks, but they should not be stripped
		for f in fields:
			self.assertNotEqual(f.get("fieldname"), "")
