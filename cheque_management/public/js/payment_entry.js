// Copyright (c) 2026, Salah and contributors
// For license information, please see license.txt
//
// Cheque capture happens on the standard Payment Entry form, so this is where a
// user picks the Cheque Type. Two jobs only:
//
//   * point paid_to / paid_from at the cheque type's clearing account, and
//   * keep the picker to types that fit this company and payment direction.
//
// The server validates the account rather than setting it (cheque_events.
// before_submit): a hook that silently rewrites paid_to would change the
// accounting of a payment behind the user's back. Setting it here instead means
// the change is visible on screen, on a draft, and can be overridden - and if it
// is overridden wrongly, submit refuses.

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		frm.set_query("custom_mfg_cheque_type", () => {
			const direction = frm.doc.payment_type === "Pay" ? "Outbound" : "Inbound";
			return {
				filters: {
					company: frm.doc.company,
					direction: direction,
					enabled: 1,
				},
			};
		});

		frm.set_query("custom_mfg_bank_account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				account_type: ["in", ["Bank", "Cash"]],
			},
		}));
	},

	custom_mfg_cheque_type(frm) {
		set_capture_account(frm);
	},

	// The date written on the cheque decides whether it is post-dated, which
	// decides which clearing account it lands in.
	reference_date(frm) {
		set_capture_account(frm);
	},

	posting_date(frm) {
		set_capture_account(frm);
	},

	mode_of_payment(frm) {
		toggle_cheque_hint(frm);
	},

	refresh(frm) {
		toggle_cheque_hint(frm);
	},
});

function set_capture_account(frm) {
	// Never touch a submitted or cancelled document: refresh fires on those too,
	// and set_value there dirties a form the user cannot save.
	if (frm.doc.docstatus !== 0) return;
	if (!frm.doc.custom_mfg_cheque_type) return;

	frappe.db.get_doc("MFG Cheque Type", frm.doc.custom_mfg_cheque_type).then((cheque_type) => {
		const post_dated =
			frm.doc.reference_date &&
			frm.doc.posting_date &&
			frappe.datetime.str_to_obj(frm.doc.reference_date) >
				frappe.datetime.str_to_obj(frm.doc.posting_date);

		const account = post_dated
			? cheque_type.post_dated_account || cheque_type.clearing_account
			: cheque_type.clearing_account;
		if (!account) return;

		const fieldname = frm.doc.payment_type === "Pay" ? "paid_from" : "paid_to";
		if (frm.doc[fieldname] === account) return;

		frm.set_value(fieldname, account).then(() => {
			frm.set_df_property(
				fieldname,
				"description",
				post_dated
					? __("Set from cheque type {0} (post-dated).", [cheque_type.name])
					: __("Set from cheque type {0}.", [cheque_type.name])
			);
		});
	});
}

function toggle_cheque_hint(frm) {
	// The flag lives on Mode of Payment, not on Payment Entry, so depends_on
	// cannot see it and it has to be looked up.
	if (!frm.doc.mode_of_payment) {
		frm.set_df_property("custom_mfg_cheque_type", "reqd", 0);
		return;
	}
	frappe.db
		.get_value("Mode of Payment", frm.doc.mode_of_payment, "custom_mfg_is_cheque")
		.then((r) => {
			const is_cheque = !!(r.message && cint(r.message.custom_mfg_is_cheque));
			frm.set_df_property("custom_mfg_cheque_type", "reqd", is_cheque);
		});
}
