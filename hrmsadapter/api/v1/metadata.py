"""
Metadata API — v1

Exposes DocType field metadata with Mobile Field Mapping overrides applied.
Flutter renders forms from this; it never reads ERPNext DocType internals.
"""
import frappe

from hrmsadapter.decorators.auth import require_mobile_auth
from hrmsadapter.services.metadata_service import MetadataService
from hrmsadapter.utils.response import error, success


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_form_metadata(doctype):
	"""Return Flutter-normalised field descriptors for a DocType."""
	if not doctype:
		return error("doctype is required.", http_status_code=400)
	if not frappe.has_permission(doctype, "read"):
		return error(f"No read permission on {doctype}.", http_status_code=403)
	try:
		fields = MetadataService.get_mobile_fields(doctype)
		return success(data={"doctype": doctype, "fields": fields})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_doctype_states(doctype):
	"""Return workflow states for a DocType (colours, labels, allowed transitions)."""
	if not doctype:
		return error("doctype is required.", http_status_code=400)
	try:
		data = frappe.call("hrms.api.get_doctype_states", doctype=doctype)
		return success(data=data or {})
	except AttributeError:
		# hrms.api.get_doctype_states may not exist on all versions
		meta = frappe.get_meta(doctype)
		states = []
		if meta.states:
			states = [{"title": s.title, "color": s.color} for s in meta.states]
		return success(data={"states": states})
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_workflow(doctype):
	"""Return active workflow definition for a DocType."""
	if not doctype:
		return error("doctype is required.", http_status_code=400)
	try:
		workflow_name = frappe.db.get_value(
			"Workflow", {"document_type": doctype, "is_active": 1}, "name"
		)
		if not workflow_name:
			return success(data=None)
		workflow = frappe.get_doc("Workflow", workflow_name)
		return success(
			data={
				"name": workflow.name,
				"states": [
					{
						"state": s.state,
						"doc_status": s.doc_status,
						"allow_edit": s.allow_edit,
						"style": s.style,
					}
					for s in workflow.states
				],
				"transitions": [
					{
						"state": t.state,
						"action": t.action,
						"next_state": t.next_state,
						"allowed": t.allowed,
					}
					for t in workflow.transitions
				],
			}
		)
	except Exception as e:
		return error(str(e), http_status_code=500)


@frappe.whitelist(methods=["GET"])
@require_mobile_auth
def get_link_options(doctype, fieldname, search_term=None):
	"""Return selectable options for a Link field (respects user permissions)."""
	if not doctype or not fieldname:
		return error("doctype and fieldname are required.", http_status_code=400)
	try:
		options = MetadataService.get_link_options(doctype, fieldname, search_term or "")
		return success(data=options)
	except Exception as e:
		return error(str(e), http_status_code=500)
