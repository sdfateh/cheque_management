# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from cheque_management.i18n import _

# Inbound cheques are assets we hold; outbound cheques are liabilities we owe.
EXPECTED_ROOT_TYPE = {"Inbound": "Asset", "Outbound": "Liability"}

ACCOUNT_FIELDS = ("clearing_account", "transit_account", "post_dated_account")


class MFGChequeType(Document):
	def validate(self):
		self.validate_transit_account()
		self.validate_accounts()
		self.validate_distinct()
		self.set_currency()

	def validate_transit_account(self):
		"""Only an inbound cheque is ever 'with the bank for collection'.

		An outbound cheque goes straight from Cheques Payable to the bank on
		Clear, so a transit account there would never be posted to.
		"""
		if self.direction == "Inbound" and not self.transit_account:
			frappe.throw(
				_("An Inbound cheque type needs an Under Collection account: it is where a deposited cheque waits until the bank clears it.")
			)
		if self.direction == "Outbound" and self.transit_account:
			frappe.throw(_("An Outbound cheque type has no Under Collection stage."))

	def validate_accounts(self):
		for fieldname in (*ACCOUNT_FIELDS, "default_bank_account"):
			account = self.get(fieldname)
			if not account:
				continue

			label = _(self.meta.get_label(fieldname))
			details = frappe.db.get_value(
				"Account",
				account,
				["company", "is_group", "disabled", "root_type", "account_type", "freeze_account"],
				as_dict=True,
			)
			if details.company != self.company:
				frappe.throw(_("{0} {1} belongs to {2}, not {3}.").format(label, account, details.company, self.company))
			if details.is_group:
				frappe.throw(_("{0} {1} is a group account. Pick a ledger.").format(label, account))
			if details.disabled:
				frappe.throw(_("{0} {1} is disabled.").format(label, account))

			if fieldname == "default_bank_account":
				continue

			expected_root = EXPECTED_ROOT_TYPE[self.direction]
			if details.root_type != expected_root:
				frappe.throw(
					_("{0} {1} is {2}, but an {3} cheque is carried in {4}.").format(
						label, account, _(details.root_type), _(self.direction), _(expected_root)
					)
				)

			# The clearing accounts are ordinary ledgers on purpose. Typing them
			# Bank or Cash would offer their balances up in the Bank Clearance
			# tool, whose account picker filters on account_type in
			# ("Bank", "Cash") (bank_clearance.js:11), and present money that is
			# still only a piece of paper as cash on the balance sheet.
			if details.account_type in ("Bank", "Cash"):
				frappe.throw(
					_(
						"{0} {1} has Account Type = {2}. Cheque clearing accounts must be ordinary "
						"ledgers with no account type: a cheque in hand is not cash, and Bank/Cash "
						"accounts are pulled into the Bank Clearance tool."
					).format(label, account, _(details.account_type))
				)

	def validate_distinct(self):
		used = [(f, self.get(f)) for f in ACCOUNT_FIELDS if self.get(f)]
		seen = {}
		for fieldname, account in used:
			if account in seen:
				frappe.throw(
					_("{0} and {1} cannot be the same account: the whole point is to see where a cheque is.").format(
						_(self.meta.get_label(seen[account])), _(self.meta.get_label(fieldname))
					)
				)
			seen[account] = fieldname

	def set_currency(self):
		"""One currency across all three accounts.

		A cheque's face value is carried in its clearing account, so the account
		cannot be denominated differently from the cheque itself.
		"""
		currencies = {}
		for fieldname in ACCOUNT_FIELDS:
			account = self.get(fieldname)
			if not account:
				continue
			currency = frappe.db.get_value("Account", account, "account_currency") or frappe.get_cached_value(
				"Company", self.company, "default_currency"
			)
			currencies.setdefault(currency, []).append(_(self.meta.get_label(fieldname)))

		if len(currencies) > 1:
			frappe.throw(
				_("All cheque accounts must share one currency, but this type mixes {0}.").format(
					", ".join(f"{c} ({', '.join(labels)})" for c, labels in currencies.items())
				)
			)
		self.currency = next(iter(currencies), None) or frappe.get_cached_value(
			"Company", self.company, "default_currency"
		)
