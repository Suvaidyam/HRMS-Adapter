"""Backfill the new enable_worklog / enable_travel flags on existing sites.

Both are new Check fields declared with `default: 1`, but HRMS Mobile Settings is
a Single: `tabSingles` holds only the keys that have actually been written, and
`frappe.db.get_singles_dict` returns nothing for a field that never has been. So
an existing settings row would read both as unset, `get_feature_flags` would
report them false, and the app would hide Worklog and Travel — the exact
opposite of the declared default.

New installs get these from `install.py`; this covers every site that already
had the doctype.

Idempotent — only writes a key that is genuinely absent, so an admin who has
deliberately switched one off is not overridden on the next migrate.
"""
import frappe

_DOCTYPE = "HRMS Mobile Settings"
_FLAGS = ("enable_worklog", "enable_travel")


def execute():
	stored = frappe.db.get_singles_dict(_DOCTYPE)
	if not stored:
		# Fresh site — after_install seeds the whole row instead.
		return

	wrote = False
	for fieldname in _FLAGS:
		if stored.get(fieldname) is None:
			frappe.db.set_single_value(_DOCTYPE, fieldname, 1)
			wrote = True

	if wrote:
		frappe.clear_cache(doctype=_DOCTYPE)
		frappe.db.commit()
