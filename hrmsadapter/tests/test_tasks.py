"""
Integration tests for the scheduled cleanup tasks.

Run with: bench run-tests --app hrmsadapter --module hrmsadapter.tests.test_tasks

Note: expire_inactive_devices runs a site-wide sweep and commits, exactly as the
nightly scheduler does. These tests assert only on their own rows.
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from hrmsadapter.services import auth_service
from hrmsadapter.tasks import token_cleanup

USER = "test-mobile-a@example.com"


class TestTokenCleanup(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings"):
			from hrmsadapter.install import _create_mobile_settings

			_create_mobile_settings()

		if not frappe.db.exists("User", USER):
			doc = frappe.new_doc("User")
			doc.email = USER
			doc.first_name = "test-mobile-a"
			doc.send_welcome_email = 0
			doc.insert(ignore_permissions=True)

		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.delete("Mobile Device", {"device_id": ("like", "test-device-%")})
		frappe.db.commit()

	def _device(self, device_id, last_login, last_active=None):
		_, refresh_hash = auth_service.generate_refresh_token()
		result = auth_service.upsert_device(
			user=USER, device_id=device_id, refresh_token_hash=refresh_hash, fcm_token="tok"
		)
		frappe.db.set_value(
			"Mobile Device",
			result["name"],
			{"last_login": last_login, "last_active": last_active},
			update_modified=False,
		)
		return result["name"]

	def test_spares_device_with_recent_login_and_null_last_active(self):
		"""last_active is NULL for every device that logged in but never called
		device.register. The old `OR last_active IS NULL` clause expired all of them
		on the first nightly run, wiping their FCM token and killing push."""
		name = self._device("test-device-fresh", last_login=now_datetime(), last_active=None)

		token_cleanup.expire_inactive_devices()

		row = frappe.get_doc("Mobile Device", name)
		self.assertEqual(row.status, "Active")
		self.assertEqual(row.fcm_token, "tok")

	def test_expires_genuinely_stale_device(self):
		stale = add_to_date(now_datetime(), days=-200)
		name = self._device("test-device-stale", last_login=stale, last_active=stale)

		token_cleanup.expire_inactive_devices()

		row = frappe.get_doc("Mobile Device", name)
		self.assertEqual(row.status, "Expired")
		self.assertEqual(row.status_reason, "Inactivity")
		self.assertFalse(row.fcm_token)
		self.assertFalse(row.refresh_token_hash)

	def test_does_not_touch_blocked_devices(self):
		stale = add_to_date(now_datetime(), days=-200)
		name = self._device("test-device-stale-blocked", last_login=stale, last_active=stale)
		auth_service.block_device("test-device-stale-blocked")

		token_cleanup.expire_inactive_devices()

		self.assertEqual(frappe.db.get_value("Mobile Device", name, "status"), "Blocked")
