"""Expense Claims API — v1"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import clamp_pagination, get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_claims(for_approval=0, limit=20, offset=0):
	limit, offset = clamp_pagination(limit, offset)
	employee = get_current_employee()
	try:
		data = frappe.call(
			"hrms.api.get_expense_claims",
			employee=employee,
			for_approval=int(for_approval),
			limit=limit + offset,
		)
		items = (data or [])[offset: offset + limit]
		return success(data={"items": items, "total": len(data or []), "limit": limit, "offset": offset})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_types():
	data = frappe.get_all(
		"Expense Claim Type",
		fields=["name", "description", "default_account"],
		order_by="name",
	)
	return success(data=data)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def create_claim(expense_date, expenses, remarks=None):
	"""
	expenses: JSON array of { expense_type, amount, description, sanctioned_amount }
	"""
	import json

	employee = get_current_employee()
	if isinstance(expenses, str):
		expenses = json.loads(expenses)

	if not expenses:
		return error("At least one expense line is required.", http_status_code=400)

	company = frappe.db.get_value("Employee", employee, "company")

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Expense Claim",
				"employee": employee,
				"posting_date": expense_date,
				"company": company,
				"remarks": remarks,
				"expenses": [
					{
						"expense_date": expense_date,
						"expense_type": e.get("expense_type"),
						"amount": e.get("amount", 0),
						"sanctioned_amount": e.get("sanctioned_amount", e.get("amount", 0)),
						"description": e.get("description", ""),
					}
					for e in expenses
				],
			}
		)
		doc.insert()
		frappe.db.commit()
		return success(data={"name": doc.name, "total_claimed_amount": doc.total_claimed_amount})
	except frappe.ValidationError as e:
		return error(str(e), "VALIDATION_ERROR", http_status_code=422)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@require_mobile_auth
def submit_claim(name):
	doc = frappe.get_doc("Expense Claim", name)
	employee = get_current_employee()
	if doc.employee != employee:
		return error("Not permitted.", http_status_code=403)
	if doc.docstatus != 0:
		return error("Only draft claims can be submitted.", http_status_code=400)
	doc.submit()
	frappe.db.commit()
	return success(data={"name": name, "docstatus": doc.docstatus})
