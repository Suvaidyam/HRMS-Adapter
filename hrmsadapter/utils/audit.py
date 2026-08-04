import frappe


def log_api_request():
	"""
	after_request hook — writes a Mobile API Log record asynchronously
	for every /api/method/hrmsadapter.* request.
	Runs only when Mobile API Log DocType exists (Phase 10+).
	"""
	try:
		request = getattr(frappe.local, "request", None)
		if not request:
			return

		path = getattr(request, "path", "") or ""
		if "hrmsadapter" not in path:
			return

		if not frappe.db.table_exists("tabMobile API Log"):
			return

		response = getattr(frappe.local, "response", {})
		status_code = getattr(frappe.local, "response", {}).get("http_status_code", 200)

		frappe.enqueue(
			"hrmsadapter.utils.audit._write_api_log",
			queue="short",
			enqueue_after_commit=True,
			user=frappe.session.user,
			device_id=getattr(frappe.local, "mobile_device_id", None),
			endpoint=path,
			method=request.method,
			ip_address=frappe.local.request_ip,
			response_code=status_code,
		)
	except Exception:
		pass


def _write_api_log(user, device_id, endpoint, method, ip_address, response_code):
	try:
		doc = frappe.new_doc("Mobile API Log")
		doc.user = user
		doc.device = device_id
		doc.endpoint = endpoint
		doc.method = method
		doc.ip_address = ip_address
		doc.response_code = response_code
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		pass
