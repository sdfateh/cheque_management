/* Copyright (c) 2026, Salah and contributors */

frappe.provide("cheque_management.reporting");

cheque_management.reporting.common_filters = function () {
	return {
		company: {
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		from_date: {
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		to_date: {
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		cheque_type: {
			fieldname: "cheque_type",
			label: __("Cheque Type"),
			fieldtype: "Link",
			options: "MFG Cheque Type",
			get_query: () => ({
				filters: { company: frappe.query_report.get_filter_value("company") },
			}),
		},
		direction: {
			fieldname: "direction",
			label: __("Direction"),
			fieldtype: "Select",
			options: ["", "Inbound", "Outbound"],
		},
		party_type: {
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Select",
			options: ["", "Customer", "Supplier"],
		},
		customer: {
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		supplier: {
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		bank_account: {
			fieldname: "bank_account",
			label: __("Bank Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value("company"),
					is_group: 0,
				},
			}),
		},
		status: {
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Post-Dated Held",
				"Received",
				"Issued",
				"Deposited",
				"Cleared",
				"Bounced",
				"Returned to Customer",
				"Replaced",
				"Cancelled",
			],
		},
		currency: {
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
		cheque_date: {
			fieldname: "cheque_date",
			label: __("Cheque Date"),
			fieldtype: "Date",
		},
		due_date: {
			fieldname: "due_date",
			label: __("Due Date"),
			fieldtype: "Date",
			description: __("Due date is the date written on the cheque."),
		},
		group_by: {
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Party", "Customer", "Supplier", "Bank", "Currency", "Cheque Type"],
			default: "Party",
		},
		limit: {
			fieldname: "limit",
			label: __("Maximum Rows"),
			fieldtype: "Int",
			default: 500,
			description: __("Detail reports are capped at 5,000 rows. Narrow the date range for larger datasets."),
		},
	};
};

cheque_management.reporting.filters = function (report_name, keys, extras) {
	const common = cheque_management.reporting.common_filters();
	const filters = keys.map((key) => common[key]).filter(Boolean);
	if (extras) filters.push(...extras);
	frappe.query_reports[report_name] = { filters };
	if (window.erpnext?.utils?.add_dimensions) {
		erpnext.utils.add_dimensions(report_name, filters.length);
	}
};

cheque_management.reporting.exception_formatter = function (value, row, column, data, default_formatter) {
	value = default_formatter(value, row, column, data);
	if (data?.status === "Exception") return `<span class="text-danger fw-bold">${value}</span>`;
	if (data?.status === "Warning") return `<span class="text-warning fw-bold">${value}</span>`;
	return value;
};
