"""
MetadataService — The Customization Adapter.

frappe.get_meta() already merges Custom Fields and Property Setters,
so ERPNext customisations are automatically visible.
We then layer Mobile Field Mapping overrides on top.

Flutter renders from the normalised descriptor list returned here;
it never reads ERPNext DocType internals directly.
"""
import frappe


SUPPORTED_FIELD_TYPES = frozenset([
	"Data", "Small Text", "Text", "Long Text", "Text Editor",
	"Int", "Float", "Currency", "Percent", "Rating",
	"Check", "Date", "Time", "Datetime", "Duration",
	"Select", "Link", "Dynamic Link",
	"Attach", "Attach Image", "Image", "Signature",
	"Table", "Table MultiSelect",
	"Section Break", "Column Break",
	"Password", "Barcode", "Color", "Geolocation",
	"HTML", "Button",
])

FLUTTER_TYPE_MAP = {
	"Data": "text",
	"Small Text": "multiline",
	"Text": "multiline",
	"Long Text": "multiline",
	"Text Editor": "rich_text",
	"Int": "integer",
	"Float": "decimal",
	"Currency": "currency",
	"Percent": "percent",
	"Rating": "rating",
	"Check": "checkbox",
	"Date": "date",
	"Time": "time",
	"Datetime": "datetime",
	"Duration": "duration",
	"Select": "dropdown",
	"Link": "link",
	"Dynamic Link": "dynamic_link",
	"Attach": "file",
	"Attach Image": "image",
	"Image": "image",
	"Signature": "signature",
	"Table": "table",
	"Table MultiSelect": "multi_select",
	"Section Break": "section",
	"Column Break": "column",
	"Password": "password",
	"Barcode": "barcode",
	"Color": "color",
	"Geolocation": "geolocation",
	"HTML": "html",
	"Button": "button",
}


class MetadataService:
	@classmethod
	def get_mobile_fields(cls, doctype: str) -> list:
		"""
		Return ordered list of Flutter field descriptors for a DocType,
		with all Mobile Field Mapping overrides applied.
		"""
		meta = frappe.get_meta(doctype)
		mappings = cls._get_field_mappings(doctype)

		fields = []
		for field in meta.fields:
			if field.fieldtype not in SUPPORTED_FIELD_TYPES:
				continue

			mapping = mappings.get(field.fieldname)
			descriptor = cls._normalize_field(field, mapping)

			if descriptor.get("hidden"):
				continue

			fields.append(descriptor)

		# Re-sort if any mapping has a display_order > 0
		if any(f.get("display_order", 0) for f in fields):
			fields.sort(key=lambda f: (f.get("display_order") or 999, f.get("_idx", 999)))

		return fields

	@classmethod
	def _get_field_mappings(cls, doctype: str) -> dict:
		cache_key = f"mobile_field_mapping:{doctype}"
		cached = frappe.cache.get_value(cache_key)
		if cached is not None:
			return cached

		rows = frappe.get_all(
			"Mobile Field Mapping",
			filters={"doctype_name": doctype, "is_active": 1},
			fields=["fieldname", "mobile_key", "label_override", "is_hidden",
					"is_readonly", "is_required_override", "display_order",
					"regex_validation", "min_value", "max_value", "help_text"],
		)
		result = {r.fieldname: r for r in rows}
		frappe.cache.set_value(cache_key, result, expires_in_sec=300)
		return result

	@classmethod
	def _normalize_field(cls, field, mapping=None) -> dict:
		m = mapping or {}
		return {
			"fieldname": m.get("mobile_key") or field.fieldname,
			"original_fieldname": field.fieldname,
			"label": m.get("label_override") or field.label or field.fieldname,
			"flutter_type": FLUTTER_TYPE_MAP.get(field.fieldtype, "text"),
			"frappe_type": field.fieldtype,
			"reqd": bool(m.get("is_required_override", field.reqd)),
			"hidden": bool(m.get("is_hidden", field.hidden)),
			"read_only": bool(m.get("is_readonly", field.read_only)),
			"options": field.options,
			"depends_on": field.depends_on,
			"description": m.get("help_text") or field.description,
			"regex_validation": m.get("regex_validation"),
			"min_value": m.get("min_value"),
			"max_value": m.get("max_value"),
			"in_list_view": bool(field.in_list_view),
			"bold": bool(field.bold),
			"default": field.default,
			"display_order": m.get("display_order") or 0,
			"_idx": field.idx,
		}

	@classmethod
	def get_link_options(cls, doctype: str, fieldname: str, search_term: str = "") -> list:
		"""Return valid options for a Link field respecting user permissions."""
		meta = frappe.get_meta(doctype)
		field = meta.get_field(fieldname)
		if not field or field.fieldtype not in ("Link", "Dynamic Link"):
			frappe.throw(f"{fieldname} is not a Link field on {doctype}.")

		target_doctype = field.options
		if not frappe.has_permission(target_doctype, "read"):
			frappe.throw(f"No read permission on {target_doctype}.", frappe.PermissionError)

		title_field = frappe.db.get_value("DocType", target_doctype, "title_field") or "name"
		filters = {}
		if search_term:
			filters = {title_field: ("like", f"%{search_term}%")}

		return frappe.get_list(
			target_doctype,
			filters=filters,
			fields=["name", title_field],
			limit=50,
			as_list=False,
		)
