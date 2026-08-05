"""Payroll API — v1"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.utils.response import error, success
from hrmsadapter.utils.validators import clamp_pagination, get_current_employee


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_salary_slips(limit=12, offset=0):
	limit, offset = clamp_pagination(limit, offset, max_limit=60)
	employee = get_current_employee()

	slips = frappe.get_all(
		"Salary Slip",
		filters={"employee": employee, "docstatus": 1},
		fields=["name", "posting_date", "start_date", "end_date",
				"gross_pay", "net_pay", "total_deduction", "currency", "company"],
		order_by="posting_date desc",
		limit=limit,
		start=offset,
	)
	total = frappe.db.count("Salary Slip", {"employee": employee, "docstatus": 1})
	return success(data={"items": slips, "total": total, "limit": limit, "offset": offset})


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_slip_detail(name):
	employee = get_current_employee()
	doc = frappe.get_doc("Salary Slip", name)
	if doc.employee != employee:
		return error("Not permitted.", http_status_code=403)

	return success(
		data={
			"name": doc.name,
			"posting_date": str(doc.posting_date),
			"start_date": str(doc.start_date),
			"end_date": str(doc.end_date),
			"gross_pay": doc.gross_pay,
			"net_pay": doc.net_pay,
			"total_deduction": doc.total_deduction,
			"currency": doc.currency,
			"earnings": [
				{"component": e.salary_component, "amount": e.amount}
				for e in doc.earnings
			],
			"deductions": [
				{"component": d.salary_component, "amount": d.amount}
				for d in doc.deductions
			],
		}
	)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_advances():
	employee = get_current_employee()
	advances = frappe.get_all(
		"Employee Advance",
		filters={"employee": employee, "docstatus": 1},
		fields=["name", "posting_date", "advance_amount", "paid_amount",
				"return_amount", "status", "purpose", "currency"],
		order_by="posting_date desc",
		limit=20,
	)
	return success(data=advances)
