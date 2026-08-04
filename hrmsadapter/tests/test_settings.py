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

	def test_jwt_secret_auto_generated(self):
		doc = frappe.get_doc("HRMS Mobile Settings")
		secret = doc.get_password("jwt_secret")
		self.assertIsNotNone(secret)
		self.assertGreater(len(secret), 32)

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
