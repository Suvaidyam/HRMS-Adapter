// Copyright (c) 2026, Suvaidyam and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mobile Device", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Blocked") return;

		frm.add_custom_button(__("Block Device Permanently"), () => {
			frappe.prompt(
				[
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Reason"),
					},
				],
				(values) => {
					frappe.call({
						method: "hrmsadapter.api.v1.device.block",
						args: { device_id: frm.doc.device_id, reason: values.reason },
						freeze: true,
						freeze_message: __("Blocking device..."),
						callback: () => frm.reload_doc(),
					});
				},
				__("Block this device? It will never be able to log in again."),
				__("Block")
			);
		}).addClass("btn-danger");
	},
});

frappe.listview_settings["Mobile Device"] = {
	get_indicator(doc) {
		const colors = {
			Active: "green",
			Revoked: "orange",
			Expired: "gray",
			Blocked: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
