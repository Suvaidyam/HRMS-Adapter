"""Notification API — v1"""
import frappe
from frappe.utils import now_datetime

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import clamp_pagination


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_notifications(unread_only=0, limit=20, offset=0):
	limit, offset = clamp_pagination(limit, offset)
	user = frappe.session.user

	filters = {"to_user": user}
	if int(unread_only):
		filters["is_read"] = 0

	items = frappe.get_all(
		"Mobile Notification",
		filters=filters,
		fields=["name", "title", "body", "deep_link", "is_read", "creation",
				"reference_doctype", "reference_name", "priority"],
		order_by="creation desc",
		limit=limit,
		start=offset,
	)
	total = frappe.db.count("Mobile Notification", filters)
	return success(data={"items": items, "total": total, "limit": limit, "offset": offset})


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def mark_read(notification_ids=None, mark_all=0):
	user = frappe.session.user

	if int(mark_all):
		frappe.db.set_value(
			"Mobile Notification",
			{"to_user": user, "is_read": 0},
			{"is_read": 1, "read_at": now_datetime()},
			update_modified=False,
		)
	elif notification_ids:
		import json
		if isinstance(notification_ids, str):
			try:
				notification_ids = json.loads(notification_ids)
			except Exception:
				notification_ids = [notification_ids]
		for nid in notification_ids:
			if frappe.db.get_value("Mobile Notification", nid, "to_user") == user:
				frappe.db.set_value(
					"Mobile Notification",
					nid,
					{"is_read": 1, "read_at": now_datetime()},
					update_modified=False,
				)
	else:
		return error("Provide notification_ids or mark_all=1.", http_status_code=400)

	frappe.db.commit()
	return success(data={"marked": True})


@frappe.whitelist(methods=["PUT"])
@require_mobile_auth
def update_fcm_token(fcm_token, device_id):
	if not fcm_token or not device_id:
		return error("fcm_token and device_id are required.", http_status_code=400)

	user = frappe.session.user
	doc_name = frappe.db.get_value(
		"Mobile Device", {"device_id": device_id, "user": user, "status": "Active"}, "name"
	)
	if not doc_name:
		return error("Device not found.", http_status_code=404)

	frappe.db.set_value(
		"Mobile Device",
		doc_name,
		{"fcm_token": fcm_token, "fcm_token_updated": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()
	return success(data={"updated": True})


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_unread_count():
	user = frappe.session.user
	count = frappe.db.count("Mobile Notification", {"to_user": user, "is_read": 0})
	return success(data={"count": count})
