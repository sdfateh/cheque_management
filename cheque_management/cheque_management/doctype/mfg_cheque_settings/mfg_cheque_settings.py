# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from cheque_management.i18n import _

# Read defaults, used when the singleton has never been saved. Frappe returns
# None for an unsaved Single's fields rather than the DocType default, mirroring
# MFGProductionOperationsSettings.
DEFAULTS = {
	"auto_mature_post_dated": 1,
	"default_fee_treatment": "Company Expense",
}


class MFGChequeSettings(Document):
	def validate(self):
		seen = set()
		for row in self.company_settings:
			if row.company in seen:
				frappe.throw(_("Row {0}: {1} already has a row.").format(row.idx, row.company))
			seen.add(row.company)
			self.validate_company_accounts(row)

	def validate_company_accounts(self, row):
		for fieldname in (
			"default_bank_account",
			"bank_charges_account",
			"exchange_gain_loss_account",
			"cost_center",
		):
			value = row.get(fieldname)
			if not value:
				continue
			doctype = "Cost Center" if fieldname == "cost_center" else "Account"
			if frappe.db.get_value(doctype, value, "company") != row.company:
				frappe.throw(
					_("Row {0}: {1} does not belong to {2}.").format(
						row.idx, _(row.meta.get_label(fieldname)), row.company
					)
				)


def get_settings():
	"""Effective global settings, falling back to DEFAULTS for an unsaved singleton."""
	doc = frappe.get_cached_doc("MFG Cheque Settings")
	return frappe._dict(
		{
			key: (doc.get(key) if doc.get(key) not in (None, "") else default)
			for key, default in DEFAULTS.items()
		}
	)


def get_company_settings(company):
	"""Per-company accounts, with the two fallbacks ERPNext already provides.

	`bank_charges_account` deliberately has no fallback: Company has no such
	default, and silently picking an expense account would misfile real money.
	"""
	doc = frappe.get_cached_doc("MFG Cheque Settings")
	row = next((r for r in doc.company_settings if r.company == company), None)

	company_defaults = frappe.get_cached_value(
		"Company", company, ["exchange_gain_loss_account", "cost_center"], as_dict=True
	) or frappe._dict()

	return frappe._dict(
		default_bank_account=(row.default_bank_account if row else None),
		bank_charges_account=(row.bank_charges_account if row else None),
		exchange_gain_loss_account=(row.exchange_gain_loss_account if row else None)
		or company_defaults.get("exchange_gain_loss_account"),
		cost_center=(row.cost_center if row else None) or company_defaults.get("cost_center"),
		default_inbound_type=(row.default_inbound_type if row else None),
		default_outbound_type=(row.default_outbound_type if row else None),
		default_fee_treatment=get_settings().default_fee_treatment,
	)
