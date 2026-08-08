"""
Integration tests for HRMS Mobile Settings and Branding API.

Run with: bench run-tests --app hrmsadapter --module hrmsadapter.tests.test_settings
"""
import frappe
from frappe.tests.utils import FrappeTestCase


class TestMobileSettings(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings"):
			from hrmsadapter.install import _create_mobile_settings
			_create_mobile_settings()

	def test_settings_singleton_exists(self):
		doc = frappe.get_doc("HRMS Mobile Settings")
		self.assertIsNotNone(doc)

	def test_no_jwt_secret_stored(self):
		"""The signing key is derived from the site, never persisted here."""
		doc = frappe.get_doc("HRMS Mobile Settings")
		self.assertIsNone(doc.meta.get_field("jwt_secret"))

		Auth = frappe.qb.Table("__Auth")
		rows = (
			frappe.qb.from_(Auth)
			.select(Auth.name)
			.where((Auth.doctype == "HRMS Mobile Settings") & (Auth.fieldname == "jwt_secret"))
			.run()
		)
		self.assertFalse(rows)

	def test_defaults_are_set(self):
		doc = frappe.get_doc("HRMS Mobile Settings")
		self.assertEqual(doc.jwt_expiry_hours, 24)
		self.assertEqual(doc.max_devices_per_user, 5)
		self.assertEqual(doc.enable_leave, 1)
		self.assertEqual(doc.enable_attendance, 1)

	def test_branding_api_no_auth(self):
		"""get_branding must be callable as guest."""
		from hrmsadapter.api.v1.settings import get_branding
		frappe.set_user("Guest")
		result = get_branding()
		self.assertIsInstance(result, dict)
		self.assertTrue(result.get("success"))
		frappe.set_user("Administrator")
