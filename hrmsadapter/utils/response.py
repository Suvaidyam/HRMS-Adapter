import frappe


API_VERSION = "1.0"


def success(data=None, message=None):
	"""Return a standardised success envelope."""
	return {
		"success": True,
		"data": data if data is not None else {},
		"message": message,
		"error": None,
		"meta": {
			"api_version": API_VERSION,
		},
	}


def error(message, error_code=None, data=None, http_status_code=400):
	frappe.local.response["http_status_code"] = http_status_code
	return {
		"success": False,
		"data": data if data is not None else {},
		"message": None,
		"error": {
			"message": message,
			"code": error_code,
		},
		"meta": {
			"api_version": API_VERSION,
		},
	}


def paginated(items, total, limit, offset):
	return success(
		data={
			"items": items,
			"total": total,
			"limit": limit,
			"offset": offset,
			"has_more": (offset + limit) < total,
		}
	)
