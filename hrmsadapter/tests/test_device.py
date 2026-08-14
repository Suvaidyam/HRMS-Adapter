"""
Integration tests for the Mobile Device lifecycle — session limit, login upsert,
permanent blocking, and request-time session validation.

Run with: bench run-tests --app hrmsadapter --module hrmsadapter.tests.test_device

Uses dedicated test users rather than Administrator, because the device limit
counts every Active device of a user — real rows on the site would otherwise make
the eviction assertions non-deterministic.
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from hrmsadapter.api.v1 import device as device_api
from hrmsadapter.services import auth_service

USER_A = "test-mobile-a@example.com"
USER_B = "test-mobile-b@example.com"


def _endpoint(fn):
	"""Strip the whitelist/auth decorators.

	require_mobile_auth reads the Authorization header via frappe.get_request_header,
	which dereferences an unbound request proxy outside an HTTP request. These checks
	target the endpoint body, so the decorators are peeled off.
	"""
	while hasattr(fn, "__wrapped__"):
		fn = fn.__wrapped__
	return fn


class TestMobileDevice(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings"):
			from hrmsadapter.install import _create_mobile_settings

			_create_mobile_settings()

		for email in (USER_A, USER_B):
			self._ensure_user(email)

		frappe.set_user("Administrator")
		self._original_max_devices = frappe.db.get_single_value(
			"HRMS Mobile Settings", "max_devices_per_user"
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		self._set_max_devices(self._original_max_devices)
		frappe.db.delete("Mobile Device", {"device_id": ("like", "test-device-%")})
		frappe.db.commit()

	# -- helpers ---------------------------------------------------------------

	def _ensure_user(self, email):
		if frappe.db.exists("User", email):
			return
		doc = frappe.new_doc("User")
		doc.email = email
		doc.first_name = email.split("@")[0]
		doc.send_welcome_email = 0
		doc.insert(ignore_permissions=True)

	def _set_max_devices(self, value):
		"""_get_settings() reads through get_cached_doc, so the cache must be cleared."""
		frappe.db.set_single_value("HRMS Mobile Settings", "max_devices_per_user", value)
		frappe.clear_document_cache("HRMS Mobile Settings", "HRMS Mobile Settings")

	def _login(self, device_id, user=USER_A, **kwargs):
		_, refresh_hash = auth_service.generate_refresh_token()
		return auth_service.upsert_device(
			user=user, device_id=device_id, refresh_token_hash=refresh_hash, **kwargs
		)

	def _active_count(self, user=USER_A):
		return frappe.db.count("Mobile Device", {"user": user, "status": "Active"})

	# -- requirement 2: one row per device, total_logins increments ------------

	def test_same_user_same_device_updates_not_inserts(self):
		first = self._login("test-device-same")
		second = self._login("test-device-same")

		self.assertEqual(first["name"], second["name"])
		self.assertEqual(first["action"], "created")
		self.assertEqual(second["action"], "updated")
		self.assertEqual(frappe.db.count("Mobile Device", {"device_id": "test-device-same"}), 1)
		self.assertEqual(frappe.db.get_value("Mobile Device", second["name"], "total_logins"), 2)

	def test_different_device_creates_new_row(self):
		first = self._login("test-device-a")
		second = self._login("test-device-b")

		self.assertNotEqual(first["name"], second["name"])
		self.assertEqual(self._active_count(), 2)

	def test_login_works_without_employee_record(self):
		"""`employee` must stay optional — making it mandatory made login raise
		MandatoryError for every user without an Active Employee row."""
		result = self._login("test-device-no-employee")
		self.assertFalse(frappe.db.get_value("Mobile Device", result["name"], "employee"))

	def test_different_user_same_device_reassigns_row(self):
		first = self._login("test-device-shared", fcm_token="stale-token")
		second = self._login("test-device-shared", user=USER_B)

		self.assertEqual(first["name"], second["name"])
		self.assertEqual(second["action"], "reassigned")

		row = frappe.get_doc("Mobile Device", second["name"])
		self.assertEqual(row.user, USER_B)
		self.assertEqual(row.total_logins, 1)
		self.assertFalse(row.fcm_token, "previous owner's push token must not survive")

	def test_save_does_not_rewrite_user_from_employee(self):
		"""A fetch_from on `user` would silently revert it to employee.user_id on
		every save, which chained into cross-user token minting via refresh."""
		result = self._login("test-device-owner-stable", user=USER_B)
		doc = frappe.get_doc("Mobile Device", result["name"])
		doc.save(ignore_permissions=True)
		doc.reload()
		self.assertEqual(doc.user, USER_B)

	# -- requirement 1: device limit -------------------------------------------

	def test_device_limit_evicts_all_excess(self):
		"""Lower the cap after enrolment (or inherit rows from the old create-only
		enforcement) — the next login must converge in one go, not evict just one."""
		self._set_max_devices(10)
		for i in range(5):
			self._login(f"test-device-limit-{i}")
		self.assertEqual(self._active_count(), 5)

		self._set_max_devices(2)
		result = self._login("test-device-limit-new")

		self.assertEqual(len(result["evicted"]), 4)
		self.assertEqual(self._active_count(), 2)

	def test_device_limit_holds_across_successive_logins(self):
		self._set_max_devices(2)
		for i in range(4):
			self._login(f"test-device-cap-{i}")

		self.assertEqual(self._active_count(), 2)

	def test_device_limit_ignores_current_device_on_relogin(self):
		self._set_max_devices(2)
		self._login("test-device-relogin-1")
		self._login("test-device-relogin-2")

		result = self._login("test-device-relogin-2")
		self.assertEqual(result["action"], "updated")
		self.assertEqual(result["evicted"], [])
		self.assertEqual(self._active_count(), 2)

	def test_evicted_device_loses_its_credentials(self):
		self._set_max_devices(1)
		first = self._login("test-device-evict-me", fcm_token="tok")
		self._login("test-device-evict-winner")

		row = frappe.get_doc("Mobile Device", first["name"])
		self.assertEqual(row.status, "Expired")
		self.assertEqual(row.status_reason, "Device Limit")
		self.assertFalse(row.refresh_token_hash)
		self.assertFalse(row.fcm_token)

	# -- requirement 4: permanent block ---------------------------------------

	def test_blocked_device_cannot_login(self):
		self._login("test-device-block")
		auth_service.block_device("test-device-block", "lost phone")

		self.assertTrue(auth_service.is_device_blocked("test-device-block"))
		with self.assertRaises(auth_service.DeviceBlockedError):
			self._login("test-device-block")

	def test_blocked_device_cannot_be_claimed_by_another_user(self):
		self._login("test-device-block-other")
		auth_service.block_device("test-device-block-other")

		with self.assertRaises(auth_service.DeviceBlockedError):
			self._login("test-device-block-other", user=USER_B)

	def test_blocked_device_cannot_be_unblocked_without_system_manager(self):
		result = self._login("test-device-unblock")
		auth_service.block_device("test-device-unblock")

		frappe.set_user(USER_A)
		try:
			doc = frappe.get_doc("Mobile Device", result["name"])
			doc.status = "Active"
			with self.assertRaises(frappe.PermissionError):
				doc.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_deactivate_device_cannot_downgrade_blocked(self):
		result = self._login("test-device-terminal")
		auth_service.block_device("test-device-terminal")

		auth_service.deactivate_device(result["name"], "Revoked", "Logout")
		self.assertEqual(frappe.db.get_value("Mobile Device", result["name"], "status"), "Blocked")

	def test_revoked_device_can_login_again(self):
		"""Non-regression: logout uses Revoked, which must stay re-loginable."""
		result = self._login("test-device-revoked")
		auth_service.deactivate_device(result["name"], "Revoked", "Logout")

		again = self._login("test-device-revoked")
		self.assertEqual(again["name"], result["name"])
		self.assertEqual(frappe.db.get_value("Mobile Device", result["name"], "status"), "Active")

	# -- token invalidation actually works ------------------------------------

	def test_deactivate_device_invalidates_refresh_token(self):
		"""refresh_token_hash used to be a Password field, so blanking the column
		left get_password() returning the old hash from `__Auth`."""
		raw, refresh_hash = auth_service.generate_refresh_token()
		result = auth_service.upsert_device(
			user=USER_A, device_id="test-device-refresh", refresh_token_hash=refresh_hash
		)

		doc = frappe.get_doc("Mobile Device", result["name"])
		self.assertTrue(auth_service.verify_refresh_token(doc, raw))

		auth_service.deactivate_device(result["name"], "Revoked", "Logout")
		doc.reload()
		self.assertFalse(auth_service.verify_refresh_token(doc, raw))

	# -- request-time session validation --------------------------------------

	def test_session_check_allows_unknown_device(self):
		auth_service.invalidate_device_state_cache("test-device-nonexistent")
		auth_service.assert_device_session_valid(
			{"sub": USER_A, "device_id": "test-device-nonexistent"}
		)

	def test_session_check_accepts_active_owner(self):
		self._login("test-device-ok")
		auth_service.assert_device_session_valid({"sub": USER_A, "device_id": "test-device-ok"})

	def test_session_check_rejects_revoked_device(self):
		result = self._login("test-device-session")
		auth_service.deactivate_device(result["name"], "Revoked", "Logout")

		with self.assertRaises(frappe.AuthenticationError):
			auth_service.assert_device_session_valid(
				{"sub": USER_A, "device_id": "test-device-session"}
			)

	def test_session_check_rejects_owner_mismatch(self):
		self._login("test-device-owner")

		with self.assertRaises(frappe.AuthenticationError):
			auth_service.assert_device_session_valid(
				{"sub": USER_B, "device_id": "test-device-owner"}
			)

	# -- register must not resurrect or clobber -------------------------------

	def test_register_does_not_resurrect_revoked_device(self):
		result = self._login("test-device-register")
		auth_service.deactivate_device(result["name"], "Revoked", "Logout")

		frappe.set_user(USER_A)
		try:
			response = _endpoint(device_api.register)(device_id="test-device-register")
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(response["success"])
		self.assertEqual(response["error"]["code"], "DEVICE_NOT_ACTIVE")
		self.assertEqual(frappe.db.get_value("Mobile Device", result["name"], "status"), "Revoked")

	def test_register_rejects_blocked_device(self):
		self._login("test-device-register-blocked")
		auth_service.block_device("test-device-register-blocked")

		frappe.set_user(USER_A)
		try:
			response = _endpoint(device_api.register)(device_id="test-device-register-blocked")
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(response["success"])
		self.assertEqual(response["error"]["code"], "DEVICE_BLOCKED")

	def test_register_does_not_clobber_refresh_token(self):
		raw, refresh_hash = auth_service.generate_refresh_token()
		result = auth_service.upsert_device(
			user=USER_A, device_id="test-device-keep", refresh_token_hash=refresh_hash
		)

		frappe.set_user(USER_A)
		try:
			_endpoint(device_api.register)(device_id="test-device-keep", app_version="2.0.0")
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Mobile Device", result["name"])
		self.assertTrue(auth_service.verify_refresh_token(doc, raw))
		self.assertEqual(doc.app_version, "2.0.0")

	def test_register_does_not_blank_app_version(self):
		self._login("test-device-version", app_version="1.2.3")

		frappe.set_user(USER_A)
		try:
			_endpoint(device_api.register)(device_id="test-device-version")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value(
				"Mobile Device", {"device_id": "test-device-version"}, "app_version"
			),
			"1.2.3",
		)

	# -- observability ---------------------------------------------------------

	def test_list_devices_shape_and_secrets(self):
		self._set_max_devices(3)
		self._login("test-device-list", fcm_token="tok")

		frappe.set_user(USER_A)
		frappe.local.mobile_device_id = "test-device-list"
		try:
			response = _endpoint(device_api.list_devices)()
		finally:
			frappe.local.mobile_device_id = None
			frappe.set_user("Administrator")

		data = response["data"]
		for key in ("items", "total", "limit", "offset", "has_more", "active_count", "max_devices"):
			self.assertIn(key, data)
		self.assertEqual(data["max_devices"], 3)
		self.assertEqual(data["active_count"], 1)

		row = next(r for r in data["items"] if r["device_id"] == "test-device-list")
		self.assertEqual(row["is_current"], 1)
		self.assertEqual(row["push_enabled"], 1)
		self.assertNotIn("fcm_token", row)
		self.assertNotIn("refresh_token_hash", row)

	def test_employee_role_has_no_mobile_device_permission(self):
		"""The doctype used to grant Employee blanket read+write, which let any
		employee flip a blocked device back to Active via /api/resource."""
		roles = [p.role for p in frappe.get_meta("Mobile Device").permissions]
		self.assertNotIn("Employee", roles)
