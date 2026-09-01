import { call } from "@sanawbar/core/lib/api";

const API = "cheque_management.api.";
const OPERATIONS = "cheque_management.cheque_operations.";

export const api = {
	searchLink: (doctype, txt, filters, options) =>
		call(
			API + "search_link",
			{ doctype, txt, filters: JSON.stringify(filters || {}) },
			options
		),
	cheques: {
		list: (filters, args = {}, options) =>
			call(
				OPERATIONS + "get_cheques",
				{
					filters: JSON.stringify(filters || {}),
					limit: args.limit,
					start: args.start,
					order_by: args.order_by,
					order_dir: args.order_dir,
				},
				options
			),
		dashboard: (filters, options) =>
			call(OPERATIONS + "get_cheque_dashboard", { filters: JSON.stringify(filters || {}) }, options),
		bulkDeposit: (cheques, posting_date) =>
			call(OPERATIONS + "bulk_deposit", { cheques: JSON.stringify(cheques || []), posting_date }),
		get: (name, options) => call(OPERATIONS + "get_cheque", { name }, options),
		quickEntry: (company, options) => call(OPERATIONS + "get_quick_entry", { company }, options),
		partyInvoices: (party_type, party, company, options) =>
			call(OPERATIONS + "get_party_invoices", { party_type, party, company }, options),
		createCapture: (payload) =>
			call(OPERATIONS + "create_cheque_capture", { payload: JSON.stringify(payload || {}) }),
		mature: (cheque, posting_date) => call(OPERATIONS + "mature", { cheque, posting_date }),
		deposit: (cheque, posting_date) => call(OPERATIONS + "deposit", { cheque, posting_date }),
		clear: (cheque, args = {}) =>
			call(OPERATIONS + "clear", {
				cheque,
				posting_date: args.posting_date,
				bank_account: args.bank_account,
			}),
		bounce: (cheque, args = {}) =>
			call(OPERATIONS + "bounce", {
				cheque,
				posting_date: args.posting_date,
				fee_amount: args.fee_amount,
				fee_treatment: args.fee_treatment,
				party_share: args.party_share,
				bank_account: args.bank_account,
				reason: args.reason,
			}),
		returnToParty: (cheque, args = {}) =>
			call(OPERATIONS + "return_to_party", {
				cheque,
				returned_on: args.returned_on,
				note: args.note,
			}),
		replace: (cheque) => call(OPERATIONS + "replace", { cheque }),
	},
};
