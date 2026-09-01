# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Whitelisted endpoints for the cheque lifecycle.

Same contract as `production_operations.py`: this module orchestrates, it never
writes a GL Entry. Every movement is a standard Journal Entry or Payment Entry
submitted through ERPNext's own accounting engine.

Three facts drive the shape of the code:

* The clearing accounts are ordinary Asset/Liability ledgers with a blank
  `account_type`. ERPNext restricts Internal Transfer legs to Bank/Cash only in
  a client-side `get_query` (payment_entry.js:51-61 and :111-119); there is no
  equivalent check in payment_entry.py, so a Payment Entry built in Python is
  free to use them. Typing them Bank would be actively harmful: Bank Clearance
  filters its account picker on account_type in ("Bank", "Cash")
  (bank_clearance.js:11), so the clearing balances would be offered up for bank
  reconciliation and presented as cash on the balance sheet.
* A clearing-to-clearing move (Maturity, Deposit) has no bank leg and no party,
  so a Payment Entry buys nothing over a Journal Entry. Clear does touch the
  bank, so it stays an Internal Transfer Payment Entry: that is what puts it in
  Bank Clearance and lets it carry a real clearance_date (Journal Entry blanks
  its own clearance_date on every validate, journal_entry.py:130).
* Every guard here is read-then-write, so every action claims the cheque row
  with SELECT ... FOR UPDATE *before* reading the guard fields. Without that,
  two concurrent calls both pass the guard and both post.
"""

import json

import frappe
from frappe.utils import cstr, flt, getdate, nowdate

from cheque_management.cheque_management.doctype.mfg_cheque_settings.mfg_cheque_settings import (
	get_company_settings,
	get_settings,
)
from cheque_management.i18n import _

CHEQUE = "MFG Cheque"
CHEQUE_TYPE = "MFG Cheque Type"
INBOUND = "Inbound"
OUTBOUND = "Outbound"

MAX_LIST_LIMIT = 200

RECHARGE = "Recharge to Party"
COMPANY_EXPENSE = "Company Expense"
SPLIT = "Split"
FEE_TREATMENTS = (RECHARGE, COMPANY_EXPENSE, SPLIT)

# The single source of truth for the state machine. The server guards and the
# SPA's button rendering both read this, so they cannot drift apart.
#   action -> direction -> (legal_from_statuses, resulting_status)
TRANSITIONS = {
	"mature": {
		INBOUND: (("Post-Dated Held",), "Received"),
		OUTBOUND: (("Post-Dated Held",), "Issued"),
	},
	"deposit": {
		INBOUND: (("Received",), "Deposited"),
	},
	"clear": {
		INBOUND: (("Deposited",), "Cleared"),
		OUTBOUND: (("Issued",), "Cleared"),
	},
	"bounce": {
		INBOUND: (("Deposited",), "Bounced"),
		OUTBOUND: (("Issued",), "Bounced"),
	},
	"return_to_party": {
		INBOUND: (("Bounced",), "Returned to Customer"),
	},
	"replace": {
		INBOUND: (("Bounced", "Returned to Customer"), "Replaced"),
		OUTBOUND: (("Bounced",), "Replaced"),
	},
}


# ------------------------------------------------------------------- claiming


def allowed_actions(status, direction):
	return [
		action
		for action, by_direction in TRANSITIONS.items()
		if direction in by_direction and status in by_direction[direction][0]
	]


def _claim(cheque, action, skip_locked=False):
	"""Serialise concurrent lifecycle calls on one cheque, then guard.

	`frappe.db.get_value(..., for_update=True)` issues SELECT ... FOR UPDATE on
	the row (frappe/database/database.py:479), so a second request blocks inside
	MariaDB until this transaction commits or rolls back and then re-reads
	committed state. `Document.lock()` is deliberately not used: it is a file
	lock, it raises instead of queueing, and it is not tied to the transaction,
	so a rollback leaves it held until the expiry.

	The document is re-read with get_doc (never get_cached_doc) *after* the
	claim, so the guards below see committed data.
	"""
	row = frappe.db.get_value(
		CHEQUE,
		cheque,
		["name", "status", "direction"],
		as_dict=True,
		for_update=True,
		skip_locked=skip_locked,
	)
	if not row:
		if skip_locked:
			return None, None
		frappe.throw(_("Cheque {0} not found.").format(cheque))

	by_direction = TRANSITIONS[action].get(row.direction)
	if not by_direction:
		frappe.throw(
			_("{0} does not apply to {1} cheques.").format(
				_(action.replace("_", " ").title()), _(row.direction)
			)
		)

	legal_from, next_status = by_direction
	if row.status not in legal_from:
		frappe.throw(
			_("{0} is only allowed from {1}. Cheque {2} is {3}.").format(
				_(action.replace("_", " ").title()),
				", ".join(_(s) for s in legal_from),
				cheque,
				_(row.status),
			)
		)

	doc = frappe.get_doc(CHEQUE, cheque)
	doc.check_permission("write")
	return doc, next_status


def _already(cheque, fieldname, label):
	if cheque.get(fieldname):
		frappe.throw(
			_("{0} has already been processed for cheque {1} (reference: {2}).").format(
				label, cheque.name, cheque.get(fieldname)
			)
		)


def _mark_downstream(cheque):
	"""Called by every action that creates a document.

	Not named `first_transaction_created`: for outbound the first financial
	transaction is the source Pay Payment Entry itself. What the flag needs to
	mean is 'this cheque has lifecycle documents of its own', which is what gates
	cancelling the capture and editing the money fields.
	"""
	if not cheque.has_downstream_entries:
		cheque.has_downstream_entries = 1
		cheque.save()


# ------------------------------------------------------------------- accounts


def _accounts(cheque):
	ct = frappe.get_cached_doc(CHEQUE_TYPE, cheque.cheque_type)
	return frappe._dict(
		clearing=ct.clearing_account,
		transit=ct.transit_account,
		post_dated=ct.post_dated_account,
		default_bank=ct.default_bank_account,
	)


def _company_currency(company):
	return frappe.get_cached_value("Company", company, "default_currency")


def _bank_account(cheque, override=None):
	bank = override or cheque.bank_account or _accounts(cheque).default_bank
	bank = bank or get_company_settings(cheque.company).default_bank_account
	if not bank:
		frappe.throw(
			_(
				"No bank account is set for cheque {0}. Set one on the cheque, on its "
				"Cheque Type, or in MFG Cheque Settings for {1}."
			).format(cheque.name, cheque.company)
		)
	details = frappe.get_cached_value(
		"Account", bank, ["company", "is_group", "disabled", "account_type"], as_dict=True
	)
	if not details or details.company != cheque.company:
		frappe.throw(_("Bank account {0} does not belong to {1}.").format(bank, cheque.company))
	if details.is_group:
		frappe.throw(_("Bank account {0} is a group account.").format(bank))
	if details.disabled:
		frappe.throw(_("Bank account {0} is disabled.").format(bank))
	if details.account_type not in ("Bank", "Cash"):
		frappe.throw(_("Account {0} is not a Bank or Cash account.").format(bank))
	return bank


def dimension_fieldnames():
	"""Standard dimensions plus any configured Accounting Dimension.

	get_accounting_dimensions() lives at
	erpnext/accounts/doctype/accounting_dimension/accounting_dimension.py:242 and
	takes no required arguments. The try/except is a cheap guard against a future
	signature change.
	"""
	fieldnames = ["cost_center", "project"]
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)

		for d in get_accounting_dimensions() or []:
			if d not in fieldnames:
				fieldnames.append(d)
	except Exception:  # noqa: BLE001 - optional ERPNext integration must degrade safely
		frappe.log_error(
			title="MFG Cheque: accounting dimension lookup failed", message=frappe.get_traceback()
		)
	return fieldnames


def _dimensions(cheque):
	meta = frappe.get_meta(CHEQUE)
	values = {f: cheque.get(f) for f in dimension_fieldnames() if meta.has_field(f) and cheque.get(f)}
	values.setdefault("cost_center", get_company_settings(cheque.company).cost_center)
	return {k: v for k, v in values.items() if v}


# ------------------------------------------------------------ journal entries


def _new_journal_entry(cheque, posting_date, remark, voucher_type="Journal Entry"):
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = voucher_type
	je.company = cheque.company
	je.posting_date = getdate(posting_date or nowdate())
	je.user_remark = remark
	# create_remarks raises MandatoryError when cheque_no is set without
	# cheque_date (journal_entry.py:930-936), so the pair is always set together.
	je.cheque_no = cheque.cheque_number
	je.cheque_date = cheque.cheque_date
	# validate_multi_currency throws unless this is set whenever any row's account
	# currency differs from the company's (journal_entry.py:852-872).
	je.multi_currency = 1 if cheque.currency != _company_currency(cheque.company) else 0
	je.custom_mfg_cheque = cheque.name
	return je


def _je_row(je, account, debit=0.0, credit=0.0, exchange_rate=1.0, dimensions=None, **kwargs):
	row = je.append("accounts", {})
	row.account = account
	row.debit_in_account_currency = flt(debit)
	row.credit_in_account_currency = flt(credit)
	# set_exchange_rate overwrites a row's rate only when it is falsy, exactly 1,
	# or the row references an invoice (journal_entry.py:887-919). A deliberate
	# rate like 0.709 survives; a company-currency account is forced to 1 anyway.
	row.exchange_rate = flt(exchange_rate) or 1
	for key, value in (dimensions or {}).items():
		if row.meta.has_field(key):
			row.set(key, value)
	for key, value in kwargs.items():
		if value is not None:
			row.set(key, value)
	return row


def _book_fx_residue(je, cheque):
	"""Balance a clearing-to-clearing move in company currency.

	The outgoing leg is relieved at the rate the cheque has been carried at and
	the incoming leg is valued at the posting date's rate, so the two balance in
	cheque currency and differ in company currency.
	validate_total_debit_and_credit (journal_entry.py:830-838) throws on any
	residue, so it is booked as a realised gain or loss.

	With the JOD-only clearing accounts this site has today, every rate is 1 and
	this is a no-op.
	"""
	precision = cheque.precision("base_amount")
	base_debit = sum(flt(r.debit_in_account_currency) * flt(r.exchange_rate) for r in je.accounts)
	base_credit = sum(flt(r.credit_in_account_currency) * flt(r.exchange_rate) for r in je.accounts)
	diff = flt(base_debit - base_credit, precision)
	if not diff:
		return

	account = get_company_settings(cheque.company).exchange_gain_loss_account
	if not account:
		frappe.throw(
			_("An exchange rate difference of {0} needs an Exchange Gain/Loss account for {1}.").format(
				diff, cheque.company
			)
		)
	_je_row(
		je,
		account,
		credit=max(0, diff),
		debit=-diff if diff < 0 else 0,
		exchange_rate=1,
		dimensions=_dimensions(cheque),
	)


def _submit(doc):
	doc.insert()
	doc.submit()
	return doc


# ------------------------------------------------------------- party rebuild


def _invoice_party_account(reference_doctype, reference_name):
	field = {"Sales Invoice": "debit_to", "Purchase Invoice": "credit_to"}.get(reference_doctype)
	if not field:
		return None
	return frappe.db.get_value(reference_doctype, reference_name, field)


def _party_allocation_rows(cheque):
	"""One row spec per allocation, so a bounce re-opens each invoice by exactly
	what the cheque paid off it.

	Journal Entry rejects a referenced row whose account is not the invoice's own
	debit_to/credit_to and whose party is not the invoice's party
	(journal_entry.py:715-727). Rather than let that block a bounce, a row that no
	longer matches is demoted to an unreferenced on-account row. Any residue
	between the allocations and the face value (the source Payment Entry's
	unallocated_amount) becomes one final unreferenced row.
	"""
	precision = cheque.precision("amount")
	rows, demoted = [], []
	allocated = 0.0

	for a in cheque.allocations:
		amount = flt(a.allocated_amount, precision)
		if not amount:
			continue
		allocated += amount
		docstatus = frappe.db.get_value(a.reference_doctype, a.reference_name, "docstatus")
		party_account = _invoice_party_account(a.reference_doctype, a.reference_name)
		if docstatus == 1 and party_account and party_account == cheque.party_account:
			rows.append(
				{
					"amount": amount,
					"reference_type": a.reference_doctype,
					"reference_name": a.reference_name,
				}
			)
		else:
			demoted.append(a.reference_name)
			rows.append({"amount": amount})

	residue = flt(flt(cheque.amount, precision) - flt(allocated, precision), precision)
	if residue > 0:
		rows.append({"amount": residue})
	if not rows:
		rows.append({"amount": flt(cheque.amount, precision)})

	return rows, demoted


def _append_party_rows(je, cheque, side, dimensions):
	"""side is 'debit' (inbound bounce: re-debit the customer) or 'credit'
	(outbound bounce: re-credit the supplier)."""
	rows, demoted = _party_allocation_rows(cheque)
	for spec in rows:
		_je_row(
			je,
			cheque.party_account,
			debit=spec["amount"] if side == "debit" else 0,
			credit=spec["amount"] if side == "credit" else 0,
			exchange_rate=cheque.exchange_rate,
			dimensions=dimensions,
			party_type=cheque.party_type,
			party=cheque.party,
			reference_type=spec.get("reference_type"),
			reference_name=spec.get("reference_name"),
		)
	return demoted


# ------------------------------------------------------- reversal availability


def _reversal_blocked(company, posting_date):
	"""Would cancelling a Journal Entry posted on `posting_date` be refused?

	Two independent gates, both read from general_ledger.py:664-781:

	* validate_accounting_period(gl_entries) at line 699 always uses the
	  *original* posting date, so a closed Accounting Period covering it blocks
	  the cancel outright.
	* check_freezing_date at line 707 uses the original posting date unless
	  Accounts Settings.enable_immutable_ledger is on, in which case it uses
	  today (lines 702-705).

	Pre-checked rather than caught blind, so we never mistake an unrelated
	ValidationError for a closed period. The caller still wraps the cancel in a
	try as a backstop.
	"""
	closed = frappe.db.sql(
		"""select ap.name from `tabAccounting Period` ap, `tabClosed Document` cd
		   where ap.name = cd.parent and cd.closed = 1
		     and cd.document_type = 'Journal Entry'
		     and ap.company = %(company)s
		     and %(date)s between ap.start_date and ap.end_date""",
		{"company": company, "date": getdate(posting_date)},
	)
	if closed:
		return _("Accounting Period {0} is closed.").format(closed[0][0])

	frozen_upto = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
	if frozen_upto:
		immutable = frappe.db.get_single_value("Accounts Settings", "enable_immutable_ledger")
		check_date = getdate(nowdate()) if immutable else getdate(posting_date)
		modifier = frappe.db.get_single_value("Accounts Settings", "frozen_accounts_modifier")
		if getdate(check_date) <= getdate(frozen_upto) and modifier not in frappe.get_roles():
			return _("Accounts are frozen up to {0}.").format(frozen_upto)

	return None


def _posting_blocked(company, posting_date):
	"""Would a new Journal Entry on this date be blocked by period controls?"""
	closed = frappe.db.sql(
		"""select ap.name from `tabAccounting Period` ap, `tabClosed Document` cd
		   where ap.name = cd.parent and cd.closed = 1
		     and cd.document_type = 'Journal Entry'
		     and ap.company = %(company)s
		     and %(date)s between ap.start_date and ap.end_date""",
		{"company": company, "date": getdate(posting_date)},
	)
	if closed:
		return _("Accounting Period {0} is closed.").format(closed[0][0])

	frozen_upto = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
	modifier = frappe.db.get_single_value("Accounts Settings", "frozen_accounts_modifier")
	if frozen_upto and getdate(posting_date) <= getdate(frozen_upto) and modifier not in frappe.get_roles():
		return _("Accounts are frozen up to {0}.").format(frozen_upto)

	return None


# ------------------------------------------------------------------ maturity


@frappe.whitelist(methods=["POST"])
def mature(cheque, posting_date=None):
	"""Post-Dated Held -> Received/Issued. Moves the cheque out of the post-dated
	account into the ordinary clearing account on the date written on it.

	Inbound is an asset move (Dr clearing / Cr post-dated); outbound is a
	liability move in the opposite direction (Dr post-dated / Cr clearing).
	"""
	doc, next_status = _claim(cheque, "mature")
	_already(doc, "maturity_journal_entry", _("Maturity"))

	accounts = _accounts(doc)
	if not accounts.post_dated:
		frappe.throw(_("Cheque Type {0} has no Post-Dated Account.").format(doc.cheque_type))

	dimensions = _dimensions(doc)
	maturity_date = getdate(posting_date or doc.cheque_date)
	blocked = _posting_blocked(doc.company, maturity_date)
	if blocked:
		# A cheque still has to leave the post-dated ledger when its date arrives.
		# If that historical date is closed, book the move today and preserve the
		# reason in the voucher instead of failing the scheduler every night.
		maturity_date = getdate(nowdate())
		if today_blocked := _posting_blocked(doc.company, maturity_date):
			frappe.throw(today_blocked)

	remark = _("Cheque {0} matured").format(doc.cheque_number)
	if blocked:
		remark = _("{0}; posted on {1} because {2}").format(remark, maturity_date, blocked)
	je = _new_journal_entry(
		doc,
		maturity_date,
		remark,
	)
	if doc.direction == INBOUND:
		_je_row(je, accounts.clearing, debit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
		_je_row(je, accounts.post_dated, credit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
	else:
		_je_row(je, accounts.post_dated, debit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
		_je_row(je, accounts.clearing, credit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
	_book_fx_residue(je, doc)
	_submit(je)

	doc.update({"maturity_journal_entry": je.name, "is_post_dated": 0, "status": next_status})
	doc.save()
	_mark_downstream(doc)
	return {
		"cheque": doc.name,
		"status": next_status,
		"journal_entry": je.name,
		"posting_date": je.posting_date,
	}


def mature_post_dated_cheques():
	"""Daily: mature every held cheque whose date has arrived.

	`skip_locked` so one cheque being worked on by a user does not stall the whole
	run, and each cheque commits on its own so one failure cannot roll back the
	others.
	"""
	if not get_settings().auto_mature_post_dated:
		return

	due = frappe.get_all(
		CHEQUE,
		filters={"status": "Post-Dated Held", "cheque_date": ["<=", nowdate()], "docstatus": ["<", 2]},
		pluck="name",
	)
	for name in due:
		try:
			doc, _next = _claim(name, "mature", skip_locked=True)
			if not doc:
				continue
			mature(name)
			frappe.db.commit()
		except Exception:  # noqa: BLE001 - each scheduled cheque is isolated
			frappe.db.rollback()
			frappe.log_error(
				title=f"MFG Cheque: maturing {name} failed", message=frappe.get_traceback()
			)


# ------------------------------------------------------------------- deposit


@frappe.whitelist(methods=["POST"])
def deposit(cheque, posting_date=None):
	"""Received -> Deposited. Clearing-to-clearing, so the bank is untouched:
	the cheque is with the bank for collection but the money is not ours yet.
	"""
	doc, next_status = _claim(cheque, "deposit")
	_already(doc, "deposit_journal_entry", _("Deposit"))

	accounts = _accounts(doc)
	if not accounts.transit:
		frappe.throw(
			_("Cheque Type {0} has no Under Collection account, so it cannot be deposited.").format(
				doc.cheque_type
			)
		)

	dimensions = _dimensions(doc)
	je = _new_journal_entry(
		doc, posting_date, _("Cheque {0} deposited for collection").format(doc.cheque_number)
	)
	_je_row(je, accounts.transit, debit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
	_je_row(je, accounts.clearing, credit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
	_book_fx_residue(je, doc)
	_submit(je)

	doc.update({"deposit_journal_entry": je.name, "status": next_status})
	doc.save()
	_mark_downstream(doc)
	return {"cheque": doc.name, "status": next_status, "journal_entry": je.name}


# --------------------------------------------------------------------- clear


@frappe.whitelist(methods=["POST"])
def clear(cheque, posting_date=None, bank_account=None):
	"""-> Cleared. The only step that touches the real bank, which is why it is an
	Internal Transfer Payment Entry rather than a Journal Entry: that is what puts
	it in front of Bank Clearance and lets it carry a clearance_date.

	Inbound  : Dr Bank            / Cr Cheques Under Collection
	Outbound : Dr Cheques Payable / Cr Bank
	"""
	doc, next_status = _claim(cheque, "clear")
	_already(doc, "clear_payment_entry", _("Clear"))

	accounts = _accounts(doc)
	bank = _bank_account(doc, bank_account)

	if doc.direction == INBOUND:
		if not doc.deposit_journal_entry:
			frappe.throw(_("Cheque {0} has not been deposited.").format(doc.name))
		# paid_from is credited, paid_to debited.
		source, target = accounts.transit, bank
	else:
		source, target = bank, accounts.clearing

	pe = _internal_transfer(doc, source, target, posting_date)
	_submit(pe)

	doc.update({"clear_payment_entry": pe.name, "status": next_status})
	doc.save()
	_mark_downstream(doc)
	return {"cheque": doc.name, "status": next_status, "payment_entry": pe.name}


def _internal_transfer(cheque, source, target, posting_date):
	"""An Internal Transfer Payment Entry for the cheque's face value.

	paid_amount is denominated in the paid_from account's currency and
	received_amount in the paid_to account's currency, so when the two differ the
	pair has to be restated through company currency; ERPNext balances the GL on
	the base amounts.
	"""
	source_currency = frappe.get_cached_value("Account", source, "account_currency") or _company_currency(
		cheque.company
	)
	target_currency = frappe.get_cached_value("Account", target, "account_currency") or _company_currency(
		cheque.company
	)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Internal Transfer"
	pe.company = cheque.company
	pe.posting_date = getdate(posting_date or nowdate())
	pe.paid_from = source
	pe.paid_to = target
	# validate_transaction_reference makes these mandatory the moment either leg is
	# an account_type = Bank account (payment_entry.py:1225-1231), which the bank
	# leg always is.
	pe.reference_no = cheque.cheque_number
	pe.reference_date = cheque.cheque_date or pe.posting_date
	pe.custom_mfg_cheque = cheque.name

	base_amount = flt(cheque.amount) * (flt(cheque.exchange_rate) or 1)
	if source_currency == cheque.currency:
		pe.paid_amount = flt(cheque.amount)
		pe.source_exchange_rate = flt(cheque.exchange_rate) or 1
	else:
		rate = _rate(source_currency, cheque.company, pe.posting_date)
		pe.paid_amount = flt(base_amount / rate)
		pe.source_exchange_rate = rate

	if target_currency == cheque.currency:
		pe.received_amount = flt(cheque.amount)
		pe.target_exchange_rate = flt(cheque.exchange_rate) or 1
	else:
		rate = _rate(target_currency, cheque.company, pe.posting_date)
		pe.received_amount = flt(base_amount / rate)
		pe.target_exchange_rate = rate

	for fieldname, value in _dimensions(cheque).items():
		if pe.meta.has_field(fieldname):
			pe.set(fieldname, value)
	return pe


def _rate(from_currency, company, posting_date):
	company_currency = _company_currency(company)
	if from_currency == company_currency:
		return 1.0
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(from_currency, company_currency, posting_date)) or 1.0


# -------------------------------------------------------------------- bounce


@frappe.whitelist(methods=["POST"])
def bounce(
	cheque,
	posting_date=None,
	fee_amount=0,
	fee_treatment=None,
	party_share=None,
	bank_account=None,
	reason=None,
):
	"""-> Bounced, in one atomic action.

	Inbound unwinds the deposit and re-opens the receivable together, so the books
	are never left in a state where the cheque has failed but the customer still
	looks paid. The deposit is unwound by cancelling its Journal Entry when that
	is possible, and by an equivalent dated reversal when the original period is
	closed or frozen - a bounce reported months later must still be recordable.

	Outbound never has a deposit; it simply restores the supplier's liability.
	"""
	doc, next_status = _claim(cheque, "bounce")
	_already(doc, "bounce_journal_entry", _("Bounce"))

	posting_date = getdate(posting_date or nowdate())
	dimensions = _dimensions(doc)
	accounts = _accounts(doc)
	mechanism = None

	if doc.direction == INBOUND:
		mechanism = _unwind_deposit(doc, posting_date, dimensions)
		relieved = accounts.clearing
	else:
		relieved = accounts.clearing

	je = _new_journal_entry(
		doc, posting_date, _("Cheque {0} bounced").format(doc.cheque_number)
	)
	if doc.direction == INBOUND:
		demoted = _append_party_rows(je, doc, "debit", dimensions)
		_je_row(je, relieved, credit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
	else:
		_je_row(je, relieved, debit=doc.amount, exchange_rate=doc.exchange_rate, dimensions=dimensions)
		demoted = _append_party_rows(je, doc, "credit", dimensions)
	_book_fx_residue(je, doc)
	_submit(je)

	updates = {
		"bounce_journal_entry": je.name,
		"bounce_date": posting_date,
		"bounce_reason": cstr(reason),
		"status": next_status,
	}
	if mechanism:
		updates["deposit_reversal_method"] = mechanism
	doc.update(updates)
	doc.save()
	_mark_downstream(doc)

	fee = _book_fee(doc, posting_date, fee_amount, fee_treatment, party_share, bank_account, dimensions)

	result = {"cheque": doc.name, "status": next_status, "journal_entry": je.name, "mechanism": mechanism}
	if fee:
		result["fee_journal_entry"] = fee
	if demoted:
		# Not an error: the cheque still bounces, but those invoices could not be
		# re-opened by reference and were re-opened on account instead.
		result["unreferenced_invoices"] = demoted
	return result


def _unwind_deposit(cheque, posting_date, dimensions):
	"""Undo the deposit leg. Returns which mechanism was used."""
	if not cheque.deposit_journal_entry:
		return None

	deposit = frappe.get_doc("Journal Entry", cheque.deposit_journal_entry)
	if deposit.docstatus == 2:
		return "Already Reversed"

	blocked = _reversal_blocked(cheque.company, deposit.posting_date)
	if not blocked:
		# A controller or site hook may have written part of the cancellation before
		# rejecting it. Keep those writes isolated so the dated-reversal fallback
		# starts from the same submitted deposit we inspected above.
		frappe.db.savepoint("unwind")
		try:
			deposit.cancel()
			frappe.db.release_savepoint("unwind")
			return "Cancellation"
		except frappe.ValidationError:
			# Backstop: the pre-check reads the same two gates ERPNext does, but a
			# site rule we do not know about can still refuse the cancel.
			frappe.db.rollback(save_point="unwind")
			blocked = _("the cancellation was refused")

	accounts = _accounts(cheque)
	je = _new_journal_entry(
		cheque,
		posting_date,
		_("Deposit of cheque {0} reversed on bounce ({1})").format(cheque.cheque_number, blocked),
	)
	_je_row(je, accounts.clearing, debit=cheque.amount, exchange_rate=cheque.exchange_rate, dimensions=dimensions)
	_je_row(je, accounts.transit, credit=cheque.amount, exchange_rate=cheque.exchange_rate, dimensions=dimensions)
	_book_fx_residue(je, cheque)
	_submit(je)
	cheque.deposit_reversal_journal_entry = je.name
	cheque.save()
	return "Dated Reversal"


def _book_fee(cheque, posting_date, fee_amount, fee_treatment, party_share, bank_account, dimensions):
	"""The bank's return fee, as its own entry.

	Kept separate from the bounce entry because it is a different event with a
	different counterparty: the bank charged us, whether or not we pass it on.
	"""
	fee_amount = flt(fee_amount)
	if not fee_amount:
		return None

	fee_treatment = fee_treatment or get_company_settings(cheque.company).default_fee_treatment
	if fee_treatment not in FEE_TREATMENTS:
		frappe.throw(
			_("Fee treatment must be one of {0}.").format(", ".join(_(t) for t in FEE_TREATMENTS))
		)
	# The supplier did not cause our outbound cheque to bounce. Even if a global
	# default or a direct API payload says otherwise, the company absorbs it.
	if cheque.direction == OUTBOUND:
		fee_treatment = COMPANY_EXPENSE
		party_share = 0

	settings = get_company_settings(cheque.company)
	bank = _bank_account(cheque, bank_account)

	if fee_treatment == RECHARGE:
		party_amount, expense_amount = fee_amount, 0.0
	elif fee_treatment == COMPANY_EXPENSE:
		party_amount, expense_amount = 0.0, fee_amount
	else:
		party_amount = flt(party_share)
		if party_amount <= 0 or party_amount >= fee_amount:
			frappe.throw(
				_("A split fee needs a party share between 0 and {0}.").format(fee_amount)
			)
		expense_amount = flt(fee_amount - party_amount)

	if expense_amount and not settings.bank_charges_account:
		frappe.throw(_("MFG Cheque Settings has no Bank Charges account for {0}.").format(cheque.company))

	je = _new_journal_entry(
		cheque,
		posting_date,
		_("Bank charge on bounced cheque {0}").format(cheque.cheque_number),
		voucher_type="Bank Entry",
	)
	if party_amount:
		_je_row(
			je,
			cheque.party_account,
			debit=party_amount,
			exchange_rate=cheque.exchange_rate,
			dimensions=dimensions,
			party_type=cheque.party_type,
			party=cheque.party,
		)
	if expense_amount:
		_je_row(je, settings.bank_charges_account, debit=expense_amount, dimensions=dimensions)
	_je_row(je, _bank_account(cheque, bank), credit=fee_amount, dimensions=dimensions)
	_book_fx_residue(je, cheque)
	_submit(je)

	cheque.update(
		{
			"bounce_fee_journal_entry": je.name,
			"fee_amount": fee_amount,
			"fee_treatment": fee_treatment,
			"party_fee_share": party_amount,
			"company_fee_share": expense_amount,
		}
	)
	cheque.save()
	return je.name


# ---------------------------------------------------------- return / replace


@frappe.whitelist(methods=["POST"])
def return_to_party(cheque, returned_on=None, note=None):
	"""Bounced -> Returned to Customer. A physical handover, deliberately with no
	accounting of its own: the bounce already restored the receivable.
	"""
	doc, next_status = _claim(cheque, "return_to_party")
	doc.update(
		{
			"status": next_status,
			"returned_on": getdate(returned_on or nowdate()),
			"returned_note": cstr(note),
		}
	)
	doc.save()
	return {"cheque": doc.name, "status": next_status}


@frappe.whitelist(methods=["POST"])
def replace(cheque):
	"""Start the replacement cheque for a bounced one.

	Returns a *draft* Payment Entry rather than posting anything: the replacement
	is a new cheque with its own number, date and possibly amount, and it must be
	captured the same way every other cheque is - through a Payment Entry that
	cheque_events turns into an MFG Cheque. The old cheque flips to Replaced when
	that entry is submitted, not here, so an abandoned draft leaves no trace.
	"""
	doc, _next_status = _claim(cheque, "replace")

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive" if doc.direction == INBOUND else "Pay"
	pe.company = doc.company
	pe.posting_date = nowdate()
	pe.party_type = doc.party_type
	pe.party = doc.party
	pe.party_account = doc.party_account
	pe.paid_amount = doc.amount
	pe.received_amount = doc.amount
	pe.custom_mfg_cheque_type = doc.cheque_type
	pe.custom_mfg_drawee_bank = doc.drawee_bank
	pe.custom_mfg_bank_account = doc.bank_account
	pe.custom_mfg_replaces = doc.name

	from cheque_management.cheque_events import capture_account

	capture = capture_account(doc.cheque_type, False)
	if doc.direction == INBOUND:
		pe.paid_from = doc.party_account
		pe.paid_to = capture
	else:
		pe.paid_from = capture
		pe.paid_to = doc.party_account

	# The replacement settles the same invoices the bounce re-opened.
	for a in doc.allocations:
		pe.append(
			"references",
			{
				"reference_doctype": a.reference_doctype,
				"reference_name": a.reference_name,
				"allocated_amount": a.allocated_amount,
			},
		)

	pe.insert()
	return {"cheque": doc.name, "payment_entry": pe.name}


# ----------------------------------------------------------------- read API


# A cheque in one of these is still money in flight: not yet collected, not yet
# written off. Everything the dashboard calls "outstanding" is one of these.
OUTSTANDING_STATUSES = ("Post-Dated Held", "Received", "Deposited", "Issued")

LIST_FIELDS = (
	"name",
	"company",
	"status",
	"direction",
	"cheque_number",
	"cheque_date",
	"is_post_dated",
	"party_type",
	"party",
	"amount",
	"base_amount",
	"currency",
	"bank_account",
	"drawee_bank",
	"cheque_type",
	"bounce_date",
)

SORTABLE = {
	"cheque_date": "cheque_date",
	"amount": "amount",
	"party": "party",
	"status": "status",
	"cheque_number": "cheque_number",
	"creation": "creation",
}


def _list_filters(filters):
	"""Translate the SPA's filter payload into frappe filters.

	Whitelisted key by key rather than passed through: this is a whitelisted
	endpoint, and handing user input straight to get_list would let a caller
	filter on fields the screen never offers.
	"""
	filters = json.loads(filters) if isinstance(filters, str) else (filters or {})

	# Built as a list of [field, op, value], not a dict: an amount or date RANGE
	# needs two conditions on one field, and a dict can only hold the last one.
	conditions = []

	direct = ("company", "party", "party_type", "bank_account")
	for key in direct:
		value = filters.get(key)
		if value not in (None, "", []):
			conditions.append([key, "=", value])

	# A multi-select arrives as a list; a single chip as a string.
	for key in ("status", "direction", "cheque_type"):
		value = filters.get(key)
		if value in (None, "", []):
			continue
		conditions.append([key, "in", value] if isinstance(value, list) else [key, "=", value])

	if filters.get("outstanding"):
		conditions.append(["status", "in", list(OUTSTANDING_STATUSES)])

	if filters.get("from_date"):
		conditions.append(["cheque_date", ">=", getdate(filters["from_date"])])
	if filters.get("to_date"):
		conditions.append(["cheque_date", "<=", getdate(filters["to_date"])])

	if filters.get("min_amount") not in (None, ""):
		conditions.append(["amount", ">=", flt(filters["min_amount"])])
	if filters.get("max_amount") not in (None, ""):
		conditions.append(["amount", "<=", flt(filters["max_amount"])])

	if filters.get("overdue"):
		# Presented to the bank and past its date with no outcome recorded.
		conditions.append(["status", "=", "Deposited"])
		conditions.append(["cheque_date", "<", getdate(nowdate())])

	return conditions, cstr(filters.get("search") or "").strip()


def _search_condition(search):
	"""or_filters for the free-text box: cheque number, party, drawee bank."""
	if not search:
		return None
	like = f"%{search}%"
	return [
		["cheque_number", "like", like],
		["party", "like", like],
		["drawee_bank", "like", like],
	]


@frappe.whitelist()
def get_cheques(filters=None, limit=50, start=0, order_by="cheque_date", order_dir="asc"):
	"""The cheque list, with the total so the UI can page through it."""
	clean, search = _list_filters(filters)
	limit = min(int(limit or 50), MAX_LIST_LIMIT)
	sort_field = SORTABLE.get(order_by, "cheque_date")
	direction = "desc" if cstr(order_dir).lower() == "desc" else "asc"

	common = {"filters": clean, "or_filters": _search_condition(search)}

	rows = frappe.get_list(
		CHEQUE,
		fields=list(LIST_FIELDS),
		# creation breaks ties so paging is stable when many cheques share a date.
		order_by=f"{sort_field} {direction}, creation {direction}",
		limit_page_length=limit,
		limit_start=int(start or 0),
		**common,
	)
	total = frappe.get_list(CHEQUE, as_list=True, limit_page_length=0, **common)

	return {
		"rows": rows,
		"total": len(total),
		"start": int(start or 0),
		"limit": limit,
		"precision": frappe.get_precision(CHEQUE, "amount"),
	}


@frappe.whitelist()
def get_cheque_dashboard(filters=None):
	"""Headline numbers and the maturity profile, under the same filters as the list.

	Two questions run cheque management: how much is in flight and where, and what
	is about to need attention. The tiles answer the first, the buckets the second.

	Amounts are summed in company currency (base_amount): a mixed-currency total in
	transaction currency would be meaningless.
	"""
	clean, search = _list_filters(filters)
	rows = frappe.get_list(
		CHEQUE,
		filters=clean,
		or_filters=_search_condition(search),
		fields=["status", "direction", "cheque_date", "amount", "base_amount", "is_post_dated"],
		limit_page_length=0,
	)

	today = getdate(nowdate())
	company = (json.loads(filters) if isinstance(filters, str) else (filters or {})).get("company")
	currency = (
		_company_currency(company) if company else frappe.defaults.get_global_default("currency")
	)

	def bucket_of(row):
		if row.status not in OUTSTANDING_STATUSES:
			return None
		if not row.cheque_date:
			return "Undated"
		days = (getdate(row.cheque_date) - today).days
		if days < 0:
			return "Overdue"
		if days <= 7:
			return "Due in 7 days"
		if days <= 30:
			return "Due in 30 days"
		if days <= 90:
			return "Due in 90 days"
		return "Later"

	tiles = {
		"in_hand": ("Received", None),
		"under_collection": ("Deposited", None),
		"issued": ("Issued", None),
		"post_dated": ("Post-Dated Held", None),
		"bounced": ("Bounced", None),
	}
	kpis = {key: {"count": 0, "amount": 0.0} for key in tiles}
	kpis["overdue"] = {"count": 0, "amount": 0.0}
	kpis["outstanding"] = {"count": 0, "amount": 0.0}

	order = ["Overdue", "Due in 7 days", "Due in 30 days", "Due in 90 days", "Later", "Undated"]
	buckets = {name: {"count": 0, "amount": 0.0} for name in order}

	for row in rows:
		base = flt(row.base_amount) or flt(row.amount)

		for key, (status, _unused) in tiles.items():
			if row.status == status:
				kpis[key]["count"] += 1
				kpis[key]["amount"] += base

		if row.status in OUTSTANDING_STATUSES:
			kpis["outstanding"]["count"] += 1
			kpis["outstanding"]["amount"] += base

		name = bucket_of(row)
		if name:
			buckets[name]["count"] += 1
			buckets[name]["amount"] += base
			if name == "Overdue":
				kpis["overdue"]["count"] += 1
				kpis["overdue"]["amount"] += base

	return {
		"kpis": kpis,
		"buckets": [{"label": name, **buckets[name]} for name in order if buckets[name]["count"]],
		"currency": currency,
		"precision": frappe.get_precision(CHEQUE, "base_amount"),
	}


@frappe.whitelist(methods=["POST"])
def bulk_deposit(cheques, posting_date=None):
	"""Deposit a batch, the way a clerk actually works: one trip to the bank.

	Each cheque commits on its own. A batch that stopped at the first failure
	would leave the clerk guessing which ones went in, so failures are collected
	and reported per cheque instead.
	"""
	names = json.loads(cheques) if isinstance(cheques, str) else (cheques or [])
	done, failed = [], []

	for name in names:
		try:
			result = deposit(name, posting_date=posting_date)
			frappe.db.commit()
			done.append(result)
		except Exception as e:  # noqa: BLE001 - return per-cheque failures to the caller
			frappe.db.rollback()
			failed.append({"cheque": name, "error": cstr(e)})

	return {"deposited": done, "failed": failed}


@frappe.whitelist()
def get_cheque(name):
	"""Detail view: the document plus what may be done to it next.

	`allowed_actions` comes from the same TRANSITIONS map the server enforces, so
	the SPA cannot offer a button the server would reject.
	"""
	doc = frappe.get_doc(CHEQUE, name)
	doc.check_permission("read")
	settings = get_company_settings(doc.company)

	return {
		"cheque": doc.as_dict(),
		"allowed_actions": allowed_actions(doc.status, doc.direction),
		"can_write": bool(doc.has_permission("write")),
		"fee_treatments": list(FEE_TREATMENTS) if doc.direction == INBOUND else [COMPANY_EXPENSE],
		"default_fee_treatment": (
			settings.default_fee_treatment if doc.direction == INBOUND else COMPANY_EXPENSE
		),
		"currency_precision": frappe.get_precision(CHEQUE, "amount"),
	}


# --------------------------------------------------------------- quick entry


@frappe.whitelist()
def get_quick_entry(company=None):
	"""Everything the capture dialog needs to render itself.

	The dialog exists because recording a cheque is the one thing this desk does
	dozens of times a day, and the desk Payment Entry form asks for far more than
	a cheque needs. Anything unusual still opens the full form - the dialog links
	to it rather than trying to grow into it.
	"""
	frappe.has_permission("Payment Entry", "create", throw=True)

	companies = frappe.get_list("Company", pluck="name", limit_page_length=0)
	company = company or frappe.defaults.get_user_default("Company") or (companies[0] if companies else None)
	settings = get_company_settings(company) if company else frappe._dict()

	types = frappe.get_all(
		CHEQUE_TYPE,
		filters={"company": company, "enabled": 1} if company else {"enabled": 1},
		fields=["name", "direction", "currency"],
		order_by="direction, name",
	)

	return {
		"company": company,
		"companies": companies,
		"cheque_types": types,
		"default_inbound_type": settings.get("default_inbound_type"),
		"default_outbound_type": settings.get("default_outbound_type"),
		"default_bank_account": settings.get("default_bank_account"),
		"currency": _company_currency(company) if company else None,
		"precision": frappe.get_precision(CHEQUE, "amount"),
		"today": nowdate(),
	}


@frappe.whitelist()
def get_party_invoices(party_type, party, company):
	"""Outstanding invoices for the party, oldest first.

	A cheque almost always settles specific invoices, and which ones matters
	later: a bounce re-opens each invoice by exactly what this cheque paid off it
	(see the allocation mirror). Getting that right at capture is much cheaper
	than reconstructing it after a bounce.
	"""
	frappe.has_permission("Payment Entry", "create", throw=True)

	doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
	party_field = "customer" if party_type == "Customer" else "supplier"

	return frappe.get_list(
		doctype,
		filters={
			party_field: party,
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "currency"],
		order_by="due_date asc, posting_date asc",
		limit_page_length=50,
	)


@frappe.whitelist(methods=["POST"])
def create_cheque_capture(payload):
	"""Capture a cheque: build its Payment Entry and submit it.

	Deliberately a Payment Entry and not a shortcut around one. Submitting it is
	what writes the GL and what makes cheque_events create the MFG Cheque, so this
	endpoint inherits every validation the desk form has - the account check, the
	direction check, the duplicate-number check - rather than reimplementing them.
	"""
	data = json.loads(payload) if isinstance(payload, str) else (payload or {})
	frappe.has_permission("Payment Entry", "create", throw=True)

	required = ("company", "cheque_type", "party_type", "party", "amount", "cheque_number", "cheque_date")
	missing = [f for f in required if not data.get(f)]
	if missing:
		frappe.throw(_("Missing: {0}").format(", ".join(_(f.replace("_", " ").title()) for f in missing)))

	ct = frappe.get_cached_doc(CHEQUE_TYPE, data["cheque_type"])
	amount = flt(data["amount"])
	if amount <= 0:
		frappe.throw(_("Amount must be greater than zero."))

	from erpnext.accounts.party import get_party_account

	from cheque_management.cheque_events import capture_account, is_post_dated

	posting_date = getdate(data.get("posting_date") or nowdate())
	post_dated = is_post_dated(data["cheque_date"], posting_date)
	clearing = capture_account(ct.name, post_dated)
	party_account = get_party_account(data["party_type"], data["party"], data["company"])

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive" if ct.direction == INBOUND else "Pay"
	pe.company = data["company"]
	pe.posting_date = posting_date
	pe.party_type = data["party_type"]
	pe.party = data["party"]
	pe.party_account = party_account
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.reference_no = data["cheque_number"]
	pe.reference_date = getdate(data["cheque_date"])
	pe.mode_of_payment = data.get("mode_of_payment")
	pe.custom_mfg_cheque_type = ct.name
	pe.custom_mfg_drawee_bank = data.get("drawee_bank")
	pe.custom_mfg_bank_account = data.get("bank_account")

	if ct.direction == INBOUND:
		pe.paid_from = party_account
		pe.paid_to = clearing
	else:
		pe.paid_from = clearing
		pe.paid_to = party_account

	# Allocate oldest first, server-side: the client sends which invoices, never
	# how much of each, so the split cannot disagree with what is outstanding now.
	remaining = amount
	for name in data.get("invoices") or []:
		if remaining <= 0:
			break
		doctype = "Sales Invoice" if data["party_type"] == "Customer" else "Purchase Invoice"
		outstanding = flt(frappe.db.get_value(doctype, name, "outstanding_amount"))
		if outstanding <= 0:
			continue
		allocated = min(outstanding, remaining)
		pe.append(
			"references",
			{"reference_doctype": doctype, "reference_name": name, "allocated_amount": allocated},
		)
		remaining -= allocated

	pe.insert()
	pe.submit()

	cheque = frappe.db.get_value("Payment Entry", pe.name, "custom_mfg_cheque")
	return {
		"payment_entry": pe.name,
		"cheque": cheque,
		"unallocated": flt(remaining),
		"status": frappe.db.get_value(CHEQUE, cheque, "status") if cheque else None,
	}
