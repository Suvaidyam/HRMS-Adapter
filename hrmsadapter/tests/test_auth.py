"""
Integration tests for hrmsadapter authentication.

Run with: bench run-tests --app hrmsadapter --module hrmsadapter.tests.test_auth
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from hrmsadapter.services import auth_service


class TestAuthService(FrappeTestCase):
	def setUp(self):
		self._ensure_settings()

	def _ensure_settings(self):
		if not frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings"):
			from hrmsadapter.install import _create_mobile_settings
			_create_mobile_settings()

	def test_generate_access_token(self):
		token = auth_service.generate_access_token("Administrator", "test-device-001")
		self.assertIsInstance(token, str)
		self.assertTrue(len(token) > 50)

	def test_validate_access_token(self):
		token = auth_service.generate_access_token("Administrator", "test-device-001")
		claims = auth_service.validate_token(token)
		self.assertEqual(claims["sub"], "Administrator")
		self.assertEqual(claims["device_id"], "test-device-001")

	def test_invalid_token_raises(self):
		with self.assertRaises(frappe.AuthenticationError):
			auth_service.validate_token("not.a.valid.jwt")

	def test_blacklist_token(self):
		import time
		from datetime import datetime, timezone

		token = auth_service.generate_access_token("Administrator", "test-device-002")
		claims = auth_service.validate_token(token)
		auth_service.blacklist_token(claims["jti"], claims["exp"])

		with self.assertRaises(frappe.AuthenticationError):
			auth_service.validate_token(token)

	def test_refresh_token_hash(self):
		raw, hashed = auth_service.generate_refresh_token()
		self.assertEqual(len(raw), 48)
		self.assertEqual(len(hashed), 64)

	def tearDown(self):
		frappe.db.delete("Mobile Device", {"device_id": ("like", "test-device-%")})
		frappe.db.commit()
