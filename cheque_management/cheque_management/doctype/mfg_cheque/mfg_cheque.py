# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""The cheque tracker.

Not submittable: this record is a tracker, not a voucher. The vouchers are the
Payment Entries and Journal Entries it points at, and they carry the GL. That is
also why there is no `amended_from` - Frappe only populates it on amend, which
only exists for submittable doctypes.
"""

import frappe
from frappe.model.document import Document

from cheque_management.i18n import _

# Editing any of these after money has moved would make the cheque disagree with
# the entries already posted against it.
LOCKED_AFTER_DOWNSTREAM = (
	"amount",
	"currency",
	"exchange_rate",
	"party",
	"party_type",
	"party_account",
	"cheque_type",
	"cheque_number",
	"company",
)

# A cancelled capture never moved money, so its number must be re-usable.
IGNORED_FOR_UNIQUENESS = ("Cancelled",)


class MFGCheque(Document):
	def validate(self):
		self.validate_created_from_payment_entry()
		self.validate_unique_cheque_number()
		self.validate_locked_fields()
		self.validate_bank_account()

	def validate_created_from_payment_entry(self):
		"""A cheque with no Payment Entry behind it has no GL behind it either.

		Every lifecycle action assumes the capture entry exists - Deposit relieves
		the clearing account the capture debited, Bounce re-opens the receivable
		the capture closed. A hand-made record would post half of each of those.
		Opening balances therefore have to be entered as Payment Entries too.
		"""
		if not self.is_new():
			return
		if self.flags.from_payment_entry:
			return
		frappe.throw(
			_(
				"An MFG Cheque is created by submitting a Payment Entry that names a Cheque Type, "
				"never by hand: without that entry the cheque has no accounting behind it."
			),
			title=_("Create the Payment Entry instead"),
		)

	def validate_unique_cheque_number(self):
		"""Scoped uniqueness, not a site-wide unique index.

		Cheque numbers repeat across banks, they repeat across customers, and a
		cheque book restarts its numbering. What must be unique is the number
		within the space that issues it: the customer for an inbound cheque, our
		own bank account for an outbound one.
		"""
		if not self.cheque_number:
			return

		filters = {
			"name": ("!=", self.name),
			"company": self.company,
			"direction": self.direction,
			"cheque_number": self.cheque_number,
			"status": ("not in", IGNORED_FOR_UNIQUENESS),
		}
		if self.direction == "Inbound":
			filters["party"] = self.party
			scope = _("customer {0}").format(self.party)
		else:
			if not self.bank_account:
				return
			filters["bank_account"] = self.bank_account
			scope = _("bank account {0}").format(self.bank_account)

		clash = frappe.db.get_value("MFG Cheque", filters, "name")
		if clash:
			frappe.throw(
				_("Cheque number {0} is already recorded for {1} on {2}.").format(
					self.cheque_number, scope, clash
				),
				title=_("Duplicate Cheque"),
			)

	def validate_locked_fields(self):
		if self.is_new() or not self.has_downstream_entries:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in LOCKED_AFTER_DOWNSTREAM:
			if self.get(fieldname) != before.get(fieldname):
				frappe.throw(
					_("{0} cannot change once this cheque has entries posted against it.").format(
						_(self.meta.get_label(fieldname))
					)
				)

	def validate_bank_account(self):
		if not self.bank_account:
			return
		company, is_group, disabled, account_type = frappe.db.get_value(
			"Account", self.bank_account, ["company", "is_group", "disabled", "account_type"]
		)
		if company != self.company:
			frappe.throw(_("Bank account {0} belongs to {1}.").format(self.bank_account, company))
		if is_group:
			frappe.throw(_("Bank account {0} is a group account.").format(self.bank_account))
		if disabled:
			frappe.throw(_("Bank account {0} is disabled.").format(self.bank_account))
		if account_type not in ("Bank", "Cash"):
			frappe.throw(_("Account {0} is not a Bank or Cash account.").format(self.bank_account))

	def on_trash(self):
		if self.status != "Cancelled" or self.has_downstream_entries:
			frappe.throw(
				_(
					"Cheque {0} is backed by accounting entries and cannot be deleted. "
					"Cancel its source Payment Entry first."
				).format(self.name)
			)
