// Copyright (c) 2026, Scopen and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Scopen Tools Settings", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("Scopen Tools Settings", {
	setup(frm) {
		frm.set_query("customization_module", () => ({
			filters: { app_name: ["not in", ["frappe", "erpnext", "hrms", "scopen_tools"]] },
		}));
	},
});