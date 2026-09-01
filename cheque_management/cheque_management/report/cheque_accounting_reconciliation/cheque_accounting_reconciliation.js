cheque_management.reporting.filters("Cheque Accounting Reconciliation", [
	"company", "to_date",
], [
	{fieldname: "tolerance", label: __("Reconciliation Tolerance"), fieldtype: "Currency", default: 0},
]);
frappe.query_reports["Cheque Accounting Reconciliation"].formatter =
	cheque_management.reporting.exception_formatter;
