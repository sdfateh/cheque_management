frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["CFO Cheque Metrics"] = {
	method: "cheque_management.cfo_dashboard.get_chart",
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{fieldname: "from_date", label: __("From Date"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("To Date"), fieldtype: "Date"},
		{fieldname: "currency", label: __("Currency"), fieldtype: "Link", options: "Currency"},
		{fieldname: "bank_account", label: __("Bank"), fieldtype: "Link", options: "Account"},
		{fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
		{fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier"},
		{fieldname: "direction", label: __("Direction"), fieldtype: "Select", options: ["", "Inbound", "Outbound"]},
		{fieldname: "forecast_days", label: __("Forecast Period"), fieldtype: "Select", options: [7, 30, 60, 90, 180], default: 30},
	],
};
