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
				server_url: "http://192.168.31.42:8002" || window.location.origin,
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
