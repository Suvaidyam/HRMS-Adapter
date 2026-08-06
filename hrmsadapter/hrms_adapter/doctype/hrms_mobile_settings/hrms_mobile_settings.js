frappe.ui.form.on("HRMS Mobile Settings", {
	refresh(frm) {
		frm.trigger("re_generate");
	},
	re_generate(frm) {
		frappe.call({
			method: "hrmsadapter.api.v1.QR_code_generator.generate_qr_code",
			args: {
				name: frm.doc.name,
				company: frm.doc.company_override,
				server_url: window.location.origin,
				expiry_in_minutes: frm.doc.qr_token_expiry_minutes || 5,
			},
			callback(r) {
				const wrapper = frm.fields_dict.qr_code.$wrapper;
				wrapper.html(`
					<div style="text-align:center">
			<img src="data:image/png;base64,${r.message}" width="220">
		  </div>
		`);
			},
		});
	},
});
