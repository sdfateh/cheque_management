import frappe


def execute():
	indexes = (
		(["company", "status", "direction", "cheque_date"], "mfg_cheque_company_status_date"),
		(["company", "party_type", "party", "status"], "mfg_cheque_company_party_status"),
		(["company", "bank_account", "status"], "mfg_cheque_company_bank_status"),
		(["cheque_type", "status"], "mfg_cheque_type_status"),
	)
	for fields, index_name in indexes:
		frappe.db.add_index("MFG Cheque", fields, index_name)
