cheque_management.reporting.filters("Cheque Cash Flow Forecast", [
	"company", "currency", "bank_account", "customer", "supplier", "direction",
], [
	{fieldname: "forecast_days", label: __("Forecast Period"), fieldtype: "Select", options: [7, 30, 60, 90, 180], default: 30},
	{fieldname: "periodicity", label: __("Group By Period"), fieldtype: "Select", options: ["Day", "Week", "Month"], default: "Day"},
]);
