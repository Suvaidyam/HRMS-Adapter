"""
NotificationService — FCM push notification dispatch, queue, and retry.

Workflow event handlers (doc_events in hooks.py) call send_to_user().
A background job does the actual FCM HTTP call and records delivery status.
process_notification_queue() is called by the scheduler every minute to
retry Failed notifications.
"""
import json

import frappe
from frappe.utils import add_to_date, now_datetime


DEEP_LINK_MAP = {
	"Leave Application": "hrms://leave/{name}",
	"Expense Claim": "hrms://expense/{name}",
	"Shift Request": "hrms://shift/{name}",
	"Attendance Request": "hrms://attendance/{name}",
	"Travel Request": "hrms://travel/{name}",
	"Loan Application": "hrms://loan/{name}",
	"Appraisal": "hrms://appraisal/{name}",
	"Employee Advance": "hrms://advance/{name}",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_to_user(
	to_user: str,
	title: str,
	body: str,
	reference_doctype: str = None,
	reference_name: str = None,
	deep_link: str = None,
	extra_data: dict = None,
	priority: str = "normal",
):
	"""Create a queued Mobile Notification and enqueue FCM dispatch."""
	if not frappe.db.table_exists("tabMobile Notification"):
		return

	if not deep_link and reference_doctype and reference_name:
		template = DEEP_LINK_MAP.get(reference_doctype, "")
		deep_link = template.format(name=reference_name) if template else ""

	doc = frappe.new_doc("Mobile Notification")
	doc.to_user = to_user
	doc.title = title
	doc.body = body
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.deep_link = deep_link
	doc.extra_data = json.dumps(extra_data) if extra_data else ""
	doc.priority = priority
	doc.status = "Pending"
	doc.insert(ignore_permissions=True)

	frappe.enqueue(
		"hrmsadapter.services.notification_service._dispatch_notification",
		name=doc.name,
		queue="default",
		enqueue_after_commit=True,
	)


def process_notification_queue():
	"""Scheduler task — retry Failed notifications due for retry."""
	if not frappe.db.table_exists("tabMobile Notification"):
		return

	pending = frappe.get_all(
		"Mobile Notification",
		filters={
			"status": "Failed",
			"retry_count": ("<", frappe.db.sql("SELECT max_retries FROM `tabMobile Notification` LIMIT 1")),
			"next_retry_at": ("<=", now_datetime()),
		},
		fields=["name"],
		limit=50,
	)
	for row in pending:
		frappe.enqueue(
			"hrmsadapter.services.notification_service._dispatch_notification",
			name=row.name,
			queue="default",
		)


# ---------------------------------------------------------------------------
# Internal FCM dispatch
# ---------------------------------------------------------------------------

def _dispatch_notification(name: str):
	if not frappe.db.table_exists("tabMobile Notification"):
		return

	doc = frappe.get_doc("Mobile Notification", name)
	if doc.status == "Sent":
		return

	settings = frappe.get_cached_doc("HRMS Mobile Settings")
	if not settings.enable_push_notifications:
		frappe.db.set_value("Mobile Notification", name, "status", "Skipped")
		return

	tokens = _get_fcm_tokens(doc.to_user)
	if not tokens:
		frappe.db.set_value("Mobile Notification", name, "status", "Skipped")
		return

	payload = _build_fcm_payload(doc)
	success_ids = []
	last_error = ""

	for token in tokens:
		try:
			msg_id = _send_fcm(settings, token, payload)
			success_ids.append(msg_id)
		except Exception as e:
			last_error = str(e)

	if success_ids:
		frappe.db.set_value(
			"Mobile Notification",
			name,
			{
				"status": "Sent",
				"sent_at": now_datetime(),
				"fcm_message_id": ",".join(success_ids),
			},
		)
	else:
		retry_count = (doc.retry_count or 0) + 1
		max_retries = doc.max_retries or 3
		backoff_minutes = 2 ** retry_count
		frappe.db.set_value(
			"Mobile Notification",
			name,
			{
				"status": "Failed",
				"retry_count": retry_count,
				"next_retry_at": add_to_date(now_datetime(), minutes=backoff_minutes),
				"failure_reason": last_error[:500],
			},
		)
	frappe.db.commit()

	# Realtime badge update (Phase 11)
	try:
		unread = frappe.db.count(
			"Mobile Notification",
			{"to_user": doc.to_user, "is_read": 0},
		)
		frappe.publish_realtime(
			event="mobile_notification",
			message={"notification_id": name, "badge_count": unread},
			user=doc.to_user,
		)
	except Exception:
		pass


def _get_fcm_tokens(user: str) -> list:
	rows = frappe.get_all(
		"Mobile Device",
		filters={"user": user, "status": "Active"},
		fields=["fcm_token"],
	)
	return [r.fcm_token for r in rows if r.fcm_token]


def _build_fcm_payload(doc) -> dict:
	data = {"notification_id": str(doc.name)}
	if doc.reference_doctype:
		data["reference_doctype"] = doc.reference_doctype
	if doc.reference_name:
		data["reference_name"] = doc.reference_name
	if doc.deep_link:
		data["deep_link"] = doc.deep_link
	if doc.extra_data:
		try:
			data.update(json.loads(doc.extra_data))
		except Exception:
			pass
	# FCM's HTTP v1 API requires every `data` value to be a string.
	data = {k: str(v) for k, v in data.items() if v is not None}

	return {
		"notification": {"title": doc.title, "body": doc.body},
		"data": data,
		"android": {"priority": "high" if doc.priority == "high" else "normal"},
	}


#: OAuth2 access tokens are valid ~1h; cache a little under that so a send
#: never races an expiry that already happened.
_FCM_TOKEN_CACHE_KEY = "hrmsadapter:fcm_access_token"
_FCM_TOKEN_CACHE_SECONDS = 50 * 60


def _get_fcm_access_token(settings) -> str:
	"""Return a cached (or freshly minted) OAuth2 bearer token for FCM v1."""
	cached = frappe.cache().get_value(_FCM_TOKEN_CACHE_KEY)
	if cached:
		return cached

	from google.auth.transport.requests import Request
	from google.oauth2 import service_account

	raw = settings.get_password("fcm_service_account_json")
	if not raw:
		raise ValueError("FCM service account JSON not configured.")

	info = json.loads(raw)
	credentials = service_account.Credentials.from_service_account_info(
		info, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
	)
	credentials.refresh(Request())

	frappe.cache().set_value(
		_FCM_TOKEN_CACHE_KEY, credentials.token, expires_in_sec=_FCM_TOKEN_CACHE_SECONDS
	)
	return credentials.token


def _send_fcm(settings, token: str, payload: dict) -> str:
	"""Send a single FCM message via the HTTP v1 API. Returns the message name/ID."""
	import requests

	project_id = settings.fcm_project_id
	if not project_id:
		raise ValueError("FCM project ID not configured.")

	access_token = _get_fcm_access_token(settings)

	response = requests.post(
		f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
		json={"message": {"token": token, **payload}},
		headers={
			"Authorization": f"Bearer {access_token}",
			"Content-Type": "application/json",
		},
		timeout=10,
	)
	if response.status_code == 401:
		# Access token was rejected (e.g. clock skew, revoked key) — drop the
		# cached one so the next attempt mints a fresh one instead of retrying
		# the same bad token for the rest of its cache window.
		frappe.cache().delete_value(_FCM_TOKEN_CACHE_KEY)
	if not response.ok:
		try:
			message = response.json().get("error", {}).get("message", response.text)
		except Exception:
			message = response.text
		raise ValueError(f"FCM error ({response.status_code}): {message}")

	return response.json().get("name", "")


# ---------------------------------------------------------------------------
# Workflow event handlers (called from hooks.py doc_events)
# ---------------------------------------------------------------------------

def _notify_approver(doc, title: str, body: str, approver_field: str = None):
	"""Generic helper to notify the approver of a document."""
	approver = getattr(doc, approver_field, None) if approver_field else None
	if not approver:
		return
	for hook in frappe.get_hooks("before_mobile_notification"):
		frappe.call(hook, doc=doc, to_user=approver, title=title, body=body)
	send_to_user(
		to_user=approver,
		title=title,
		body=body,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)
	for hook in frappe.get_hooks("after_mobile_notification"):
		frappe.call(hook, doc=doc, to_user=approver)


def _notify_employee(doc, title: str, body: str):
	"""Notify the employee who owns a document."""
	user = frappe.db.get_value("Employee", doc.employee, "user_id")
	if not user:
		return
	send_to_user(
		to_user=user,
		title=title,
		body=body,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)


def on_leave_application_update(doc, method=None):
	# This app's Leave Application workflow never sets docstatus to 1 (every
	# workflow state keeps doc_status "0" — confirmed on staging), so Frappe's
	# on_submit event never fires here. The only reliable signal that the
	# employee has sent the request for approval is workflow_state actually
	# changing to the TL-pending state, whether that happened via the mobile
	# app's WorkflowActionBar or Desk.
	if (
		doc.has_value_changed("workflow_state")
		and doc.workflow_state == "Request Pending for TL Approval"
	):
		_notify_approver(
			doc,
			title="Leave Application Submitted",
			body=f"{doc.employee_name} applied for {doc.leave_type} leave.",
			approver_field="leave_approver",
		)
	if doc.status in ("Approved", "Rejected"):
		_notify_employee(
			doc,
			title=f"Leave Application {doc.status}",
			body=f"Your {doc.leave_type} leave has been {doc.status.lower()}.",
		)


def on_leave_application_cancel(doc, method=None):
	_notify_employee(
		doc,
		title="Leave Application Cancelled",
		body=f"Your {doc.leave_type} leave application has been cancelled.",
	)


def on_expense_claim_update(doc, method=None):
	# Same reasoning as on_leave_application_update: this workflow's states
	# all keep doc_status "0", so on_submit never fires even though the app
	# already calls apply_workflow('Submit For TL Approval') right after
	# creating the claim.
	if (
		doc.has_value_changed("workflow_state")
		and doc.workflow_state == "Request Pending for TL Approval"
	):
		_notify_approver(
			doc,
			title="Expense Claim Submitted",
			body=f"{doc.employee_name} submitted an expense claim of {doc.total_claimed_amount}.",
			approver_field="expense_approver",
		)
	if doc.approval_status in ("Approved", "Rejected"):
		_notify_employee(
			doc,
			title=f"Expense Claim {doc.approval_status}",
			body=f"Your expense claim has been {doc.approval_status.lower()}.",
		)


def on_shift_request_submit(doc, method=None):
	_notify_approver(
		doc,
		title="Shift Request Submitted",
		body=f"{doc.employee_name} requested a shift change.",
		approver_field="approver",
	)


def on_shift_request_update(doc, method=None):
	if doc.status in ("Approved", "Rejected"):
		_notify_employee(
			doc,
			title=f"Shift Request {doc.status}",
			body=f"Your shift request has been {doc.status.lower()}.",
		)


def on_attendance_request_submit(doc, method=None):
	_notify_employee(
		doc,
		title="Attendance Request Submitted",
		body="Your attendance request is pending approval.",
	)


def on_travel_request_submit(doc, method=None):
	_notify_approver(
		doc,
		title="Travel Request Submitted",
		body=f"{doc.employee_name} submitted a travel request.",
		approver_field="approver",
	)


def on_travel_request_update(doc, method=None):
	if getattr(doc, "approval_status", None) in ("Approved", "Rejected"):
		_notify_employee(
			doc,
			title=f"Travel Request {doc.approval_status}",
			body=f"Your travel request has been {doc.approval_status.lower()}.",
		)


def on_loan_application_submit(doc, method=None):
	_notify_approver(
		doc,
		title="Loan Application Submitted",
		body=f"{doc.employee_name} applied for a loan.",
		approver_field="loan_officer",
	)


def on_loan_application_update(doc, method=None):
	if getattr(doc, "status", None) in ("Approved", "Rejected"):
		_notify_employee(
			doc,
			title=f"Loan Application {doc.status}",
			body=f"Your loan application has been {doc.status.lower()}.",
		)


def on_appraisal_submit(doc, method=None):
	_notify_employee(
		doc,
		title="Appraisal Submitted",
		body="Your appraisal has been submitted for review.",
	)


def on_advance_update(doc, method=None):
	if getattr(doc, "status", None) == "Paid":
		_notify_employee(
			doc,
			title="Employee Advance Paid",
			body=f"Your advance of {doc.advance_amount} has been paid.",
		)
