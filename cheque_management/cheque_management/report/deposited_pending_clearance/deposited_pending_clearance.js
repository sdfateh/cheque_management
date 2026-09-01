cheque_management.reporting.filters("Deposited Pending Clearance", [
	"company", "from_date", "to_date", "cheque_type", "customer", "bank_account",
	"currency", "limit",
], [
	{fieldname: "aging_threshold_1", label: __("First Threshold"), fieldtype: "Int", default: 2},
	{fieldname: "aging_threshold_2", label: __("Second Threshold"), fieldtype: "Int", default: 5},
	{fieldname: "aging_threshold_3", label: __("Third Threshold"), fieldtype: "Int", default: 10},
]);
