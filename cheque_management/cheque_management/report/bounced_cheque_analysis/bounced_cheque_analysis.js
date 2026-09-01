cheque_management.reporting.filters("Bounced Cheque Analysis", [
	"company", "from_date", "to_date", "currency",
], [
	{fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: ["Customer", "Supplier", "Bank", "Month"], default: "Customer"},
	{fieldname: "repeated_bounce_count", label: __("Repeated Bounce Threshold"), fieldtype: "Int", default: 2},
]);
