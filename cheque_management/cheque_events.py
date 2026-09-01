# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Payment Entry hooks: cheque capture.

Split across three events on purpose.

* `validate` runs on every save, including saves that have nothing to do with
  cheques, so it only checks what is already filled in. Throwing here on missing
  cheque fields would make a draft Payment Entry unsaveable - you could not start
  one and finish it later.
* `before_submit` is where completeness and account correctness are enforced:
  the last moment before GL exists, and the only place a hard throw is fair.
* `on_submit` creates the MFG Cheque record, after ERPNext's own accounting
  engine has written the capture entries.
"""

import frappe
from frappe.utils import add_days, flt, getdate

from cheque_management.i18n import _

CHEQUE = "MFG Cheque"
CHEQUE_TYPE = "MFG Cheque Type"

# A cheque date this far ahead is almost always a mistyped year.
FAR_FUTURE_DAYS = 365


def _is_cheque_payment(pe):
	"""A Payment Entry is a cheque iff it names a Cheque Type.

	The Mode of Payment flag only makes the type *mandatory*; it is not the
	trigger, so an integration that posts without a Mode of Payment still works.
	"""
	return bool(pe.get("custom_mfg_cheque_type"))


def _mode_requires_cheque(pe):
	if not pe.mode_of_payment:
		return False
	return bool(frappe.db.get_value("Mode of Payment", pe.mode_of_payment, "custom_mfg_is_cheque"))


def is_post_dated(cheque_date, posting_date):
	"""Post-dated means the date written on the cheque is in the future relative
	to when it is booked - not that some separate due date is later than it.
	"""
	if not cheque_date or not posting_date:
		return False
	return getdate(cheque_date) > getdate(posting_date)


def capture_account(cheque_type, post_dated):
	ct = frappe.get_cached_doc(CHEQUE_TYPE, cheque_type)
	if not ct.enabled:
		frappe.throw(_("Cheque Type {0} is disabled.").format(cheque_type))
	account = ct.post_dated_account if post_dated else ct.clearing_account
	if not account:
		frappe.throw(
			_("Cheque Type {0} has no {1} configured.").format(
				cheque_type, _("Post-Dated Account") if post_dated else _("Clearing Account")
			)
		)
	return account


def _cheque_face_value(pe):
	"""(amount, currency, exchange_rate, base_amount) of the leg that lands in
	the clearing account.

	Stated once, explicitly: for a Receive the clearing account is `paid_to`, so
	the cheque's face value is `received_amount`; for a Pay it is `paid_from`, so
	the face value is `paid_amount`.
	"""
	if pe.payment_type == "Receive":
		return (
			flt(pe.received_amount),
			pe.paid_to_account_currency,
			flt(pe.target_exchange_rate),
			flt(pe.base_received_amount),
		)
	return (
		flt(pe.paid_amount),
		pe.paid_from_account_currency,
		flt(pe.source_exchange_rate),
		flt(pe.base_paid_amount),
	)


# --------------------------------------------------------------------- hooks


def validate(doc, method=None):
	"""Cheap consistency only. Never blocks saving a draft."""
	if not _is_cheque_payment(doc):
		return

	ct = frappe.get_cached_doc(CHEQUE_TYPE, doc.custom_mfg_cheque_type)

	if ct.company and doc.company and ct.company != doc.company:
		frappe.throw(
			_("Cheque Type {0} belongs to {1}, not {2}.").format(
				doc.custom_mfg_cheque_type, ct.company, doc.company
			)
		)

	if doc.payment_type == "Receive" and ct.direction != "Inbound":
		frappe.throw(
			_("{0} is an Outbound cheque type; a Receive payment needs an Inbound one.").format(ct.name)
		)
	if doc.payment_type == "Pay" and ct.direction != "Outbound":
		frappe.throw(
			_("{0} is an Inbound cheque type; a Pay payment needs an Outbound one.").format(ct.name)
		)
	if doc.payment_type == "Internal Transfer":
		frappe.throw(_("An Internal Transfer cannot itself be a cheque capture."))


def before_submit(doc, method=None):
	"""Completeness and account correctness, enforced at the last safe moment."""
	if _mode_requires_cheque(doc) and not _is_cheque_payment(doc):
		frappe.throw(
			_("Mode of Payment {0} is a cheque mode, so a Cheque Type is required.").format(
				doc.mode_of_payment
			)
		)
	if not _is_cheque_payment(doc):
		return

	if not doc.reference_no:
		frappe.throw(_("Cheque/Reference No is the cheque number and is required."))
	if not doc.reference_date:
		frappe.throw(_("Cheque/Reference Date is the date written on the cheque and is required."))
	if doc.payment_type == "Receive" and doc.party_type != "Customer":
		frappe.throw(_("An inbound cheque must be received from a Customer."))
	if doc.payment_type == "Pay" and doc.party_type != "Supplier":
		frappe.throw(_("An outbound cheque must be paid to a Supplier."))

	if getdate(doc.reference_date) > getdate(add_days(doc.posting_date, FAR_FUTURE_DAYS)):
		frappe.throw(
			_("Cheque date {0} is more than a year after the posting date. Check the year.").format(
				doc.reference_date
			)
		)

	post_dated = is_post_dated(doc.reference_date, doc.posting_date)
	expected = capture_account(doc.custom_mfg_cheque_type, post_dated)

	# We validate, never set. Auto-setting here would silently change the
	# accounting of a payment; the client script sets it as a visible convenience
	# while the document is still a draft (public/js/payment_entry.js).
	if doc.payment_type == "Receive" and doc.paid_to != expected:
		frappe.throw(
			_("Paid To must be {0} for cheque type {1}{2}.").format(
				expected, doc.custom_mfg_cheque_type, _(" (post-dated)") if post_dated else ""
			)
		)
	if doc.payment_type == "Pay" and doc.paid_from != expected:
		frappe.throw(
			_("Paid From must be {0} for cheque type {1}{2}.").format(
				expected, doc.custom_mfg_cheque_type, _(" (post-dated)") if post_dated else ""
			)
		)

	_validate_replacement(doc)


def on_submit(doc, method=None):
	if not _is_cheque_payment(doc):
		return
	if doc.get("custom_mfg_cheque"):
		return

	existing = frappe.db.get_value(CHEQUE, {"source_payment_entry": doc.name}, "name")
	if existing:
		doc.custom_mfg_cheque = existing
		doc.save()
		return

	post_dated = is_post_dated(doc.reference_date, doc.posting_date)
	amount, currency, exchange_rate, base_amount = _cheque_face_value(doc)
	ct = frappe.get_cached_doc(CHEQUE_TYPE, doc.custom_mfg_cheque_type)

	cheque = frappe.new_doc(CHEQUE)
	cheque.company = doc.company
	cheque.cheque_type = doc.custom_mfg_cheque_type
	cheque.direction = ct.direction
	cheque.cheque_number = doc.reference_no
	cheque.cheque_date = doc.reference_date
	cheque.is_post_dated = 1 if post_dated else 0
	cheque.drawee_bank = doc.get("custom_mfg_drawee_bank")
	cheque.bank_account = doc.get("custom_mfg_bank_account") or ct.default_bank_account
	cheque.party_type = doc.party_type
	cheque.party = doc.party
	cheque.party_account = doc.party_account
	cheque.currency = currency
	cheque.amount = amount
	cheque.exchange_rate = exchange_rate or 1
	cheque.base_amount = base_amount
	cheque.source_payment_entry = doc.name
	cheque.replaces = doc.get("custom_mfg_replaces")
	cheque.status = _initial_status(ct.direction, post_dated)

	# Mirror the whole allocation, not just the first row: a bounce has to
	# re-open each invoice by exactly what this cheque paid off it.
	for ref in doc.get("references") or []:
		if not flt(ref.allocated_amount):
			continue
		cheque.append(
			"allocations",
			{
				"reference_doctype": ref.reference_doctype,
				"reference_name": ref.reference_name,
				"allocated_amount": flt(ref.allocated_amount),
			},
		)

	for fieldname, value in _dimension_values(doc).items():
		if cheque.meta.has_field(fieldname):
			cheque.set(fieldname, value)

	# The only ignore_permissions in the module: the Payment Entry submit that
	# triggered this was already permission-checked, and the cheque record is a
	# derived artifact of it. Whoever may submit the payment may not hold create
	# on MFG Cheque - and by design nobody does, creation by hand is blocked.
	cheque.flags.from_payment_entry = True
	cheque.flags.ignore_permissions = True
	cheque.insert()

	# Persist through the Payment Entry controller and keep this instance
	# consistent too. A caller may submit and immediately
	# cancel the same object in one request; on_cancel must see the derived cheque
	# without requiring a reload from the database first.
	doc.custom_mfg_cheque = cheque.name
	doc.save()

	if cheque.replaces:
		original = frappe.get_doc(CHEQUE, cheque.replaces)
		original.update({"status": "Replaced", "replaced_by": cheque.name})
		# The submitted Payment Entry authorizes this derived tracker update.
		original.save(ignore_permissions=True)


def on_cancel(doc, method=None):
	"""A capture may only be unwound while the cheque has no life of its own."""
	name = doc.get("custom_mfg_cheque")
	if not name:
		return

	_downstream_status, downstream, replaces = frappe.db.get_value(
		CHEQUE,
		name,
		["status", "has_downstream_entries", "replaces"],
		for_update=True,
	)
	if downstream:
		frappe.throw(
			_(
				"Cannot cancel {0}: cheque {1} already has lifecycle entries of its own. "
				"Bounce or reverse the cheque first."
			).format(doc.name, name)
		)
	cheque = frappe.get_doc(CHEQUE, name)
	cheque.status = "Cancelled"
	# The Payment Entry cancellation authorizes its derived tracker update.
	cheque.save(ignore_permissions=True)

	# Cancelling a replacement capture cancels the replacement cheque too. Put
	# the original back where it was so it can be returned or replaced again.
	if replaces:
		original = frappe.db.get_value(
			CHEQUE,
			replaces,
			["replaced_by", "returned_on"],
			as_dict=True,
			for_update=True,
		)
		if original and original.replaced_by == name:
			original_doc = frappe.get_doc(CHEQUE, replaces)
			original_doc.update(
				{
					"status": "Returned to Customer" if original.returned_on else "Bounced",
					"replaced_by": None,
				}
			)
			original_doc.save(ignore_permissions=True)


def _validate_replacement(pe):
	"""Claim and validate the original before a replacement is submitted.

	A draft may sit open while another clerk replaces the same cheque, so the
	guard belongs at submit time, in the same transaction that creates the new
	cheque and marks the old one Replaced.
	"""
	original_name = pe.get("custom_mfg_replaces")
	if not original_name:
		return

	original = frappe.db.get_value(
		CHEQUE,
		original_name,
		["status", "direction", "company", "party_type", "party", "replaced_by"],
		as_dict=True,
		for_update=True,
	)
	if not original:
		frappe.throw(_("Cheque {0} to replace was not found.").format(original_name))

	legal_statuses = (
		("Bounced", "Returned to Customer") if original.direction == "Inbound" else ("Bounced",)
	)
	if original.status not in legal_statuses or original.replaced_by:
		frappe.throw(
			_("Cheque {0} is no longer available for replacement.").format(original_name)
		)

	expected_direction = "Inbound" if pe.payment_type == "Receive" else "Outbound"
	if original.direction != expected_direction:
		frappe.throw(_("The replacement must have the same direction as cheque {0}.").format(original_name))
	if original.company != pe.company:
		frappe.throw(_("The replacement must belong to the same company as cheque {0}.").format(original_name))
	if original.party_type != pe.party_type or original.party != pe.party:
		frappe.throw(_("The replacement must use the same party as cheque {0}.").format(original_name))


def _initial_status(direction, post_dated):
	if post_dated:
		return "Post-Dated Held"
	return "Received" if direction == "Inbound" else "Issued"


def _dimension_values(source):
	from cheque_management.cheque_operations import dimension_fieldnames

	return {
		f: source.get(f) for f in dimension_fieldnames() if source.meta.has_field(f) and source.get(f)
	}
