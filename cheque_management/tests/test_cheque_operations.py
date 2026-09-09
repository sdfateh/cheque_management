# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Lifecycle tests for the cheque module.

Every test asserts the GL it produced, not just the status it landed on: a status
flip with the wrong posting behind it is the bug class this module exists to
prevent, and it is invisible to a status-only assertion.

The fixtures build their own company so the tests never depend on a site's chart
of accounts, and so the clearing accounts are guaranteed to be ordinary ledgers.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from cheque_management import api as cheque_api
from cheque_management import cfo_dashboard, reporting
from cheque_management import cheque_operations as ops

CHEQUE_DT = "MFG Cheque"

CUSTOMER = "_Test Cheque Customer"
SUPPLIER = "_Test Cheque Supplier"
# The dashboard tests count rows, so they need a party nobody else writes to:
# bulk_deposit() commits per cheque by design, which defeats the per-test
# rollback and would otherwise let one test's cheques show up in another's totals.


COMPANY = "_Test Cheque Co"
ABBR = "_TCQ"


def acc(name):
	return f"{name} - {ABBR}"


def make_account(account_name, parent, root_type, account_type=None):
	name = acc(account_name)
	if frappe.db.exists("Account", name):
		return name
	return frappe.get_doc(
		{
			"doctype": "Account",
			"company": COMPANY,
			"account_name": account_name,
			"parent_account": acc(parent),
			"root_type": root_type,
			"account_type": account_type,
			"is_group": 0,
		}
	).insert().name


class TestChequeOperations(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# bulk_deposit() commits per cheque on purpose (a clerk must know which of
		# a batch went in), which defeats FrappeTestCase's per-test rollback. A
		# per-run tag keeps each run's cheque numbers unique and lets the counting
		# tests scope themselves with `search`.
		cls.RUN = frappe.generate_hash(length=6)
		cls.build_company()
		cls.build_accounts()
		cls.build_cheque_types()
		cls.build_settings()
		cls.build_parties()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		"""Remove what the committing tests left behind.

		bulk_deposit() commits per cheque by design, so those rows survive
		FrappeTestCase's rollback and would otherwise pile up in the site - and
		show up in a real dashboard, since the test company is a real company.
		Deleted with SQL because cancelling each submitted voucher through the
		controller would fight the very guards under test.
		"""
		for table in (
			"GL Entry",
			"Journal Entry Account",
			"Journal Entry",
			"Payment Entry Reference",
			"Payment Entry",
			"MFG Cheque Allocation",
			"MFG Cheque",
		):
			if table in ("Journal Entry Account", "Payment Entry Reference", "MFG Cheque Allocation"):
				parent_table = {
					"Journal Entry Account": "Journal Entry",
					"Payment Entry Reference": "Payment Entry",
					"MFG Cheque Allocation": "MFG Cheque",
				}[table]
				frappe.db.sql(
					f"""delete from `tab{table}` where parent in
					    (select name from `tab{parent_table}` where company = %s)""",
					COMPANY,
				)
			else:
				frappe.db.sql(f"delete from `tab{table}` where company = %s", COMPANY)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def build_company(cls):
		if frappe.db.exists("Company", COMPANY):
			return
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY,
				"abbr": ABBR,
				"default_currency": "JOD",
				"country": "Jordan",
			}
		).insert()

	@classmethod
	def build_accounts(cls):
		# Deliberately no account_type on the clearing ledgers: a cheque in hand is
		# not cash, and Bank/Cash accounts get pulled into Bank Clearance.
		cls.in_hand = make_account("Cheques in Hand", "Current Assets", "Asset")
		cls.transit = make_account("Cheques Under Collection", "Current Assets", "Asset")
		cls.post_dated = make_account("Post-Dated Cheques Receivable", "Current Assets", "Asset")
		cls.payable = make_account("Cheques Payable", "Current Liabilities", "Liability")
		cls.post_dated_payable = make_account(
			"Post-Dated Cheques Payable", "Current Liabilities", "Liability"
		)
		cls.charges = make_account("Bank Charges", "Indirect Expenses", "Expense")
		cls.bank = make_account("Test Bank", "Bank Accounts", "Asset", account_type="Bank")
		cls.receivable = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
		)
		cls.creditor = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_type": "Payable", "is_group": 0}, "name"
		)
		cls.cost_center = frappe.db.get_value(
			"Cost Center", {"company": COMPANY, "is_group": 0}, "name"
		)

	@classmethod
	def build_cheque_types(cls):
		if not frappe.db.exists("MFG Cheque Type", f"Inbound - {ABBR}"):
			frappe.get_doc(
				{
					"doctype": "MFG Cheque Type",
					"cheque_type_name": f"Inbound - {ABBR}",
					"company": COMPANY,
					"direction": "Inbound",
					"clearing_account": cls.in_hand,
					"transit_account": cls.transit,
					"post_dated_account": cls.post_dated,
				}
			).insert()
		cls.inbound_type = f"Inbound - {ABBR}"
		if not frappe.db.exists("MFG Cheque Type", f"Outbound - {ABBR}"):
			frappe.get_doc(
				{
					"doctype": "MFG Cheque Type",
					"cheque_type_name": f"Outbound - {ABBR}",
					"company": COMPANY,
					"direction": "Outbound",
					"clearing_account": cls.payable,
					"post_dated_account": cls.post_dated_payable,
				}
			).insert()
		cls.outbound_type = f"Outbound - {ABBR}"

	@classmethod
	def build_settings(cls):
		settings = frappe.get_single("MFG Cheque Settings")
		row = next((r for r in settings.company_settings if r.company == COMPANY), None)
		if not row:
			row = settings.append("company_settings", {"company": COMPANY})
		row.default_bank_account = cls.bank
		row.bank_charges_account = cls.charges
		settings.save()

	@classmethod
	def build_parties(cls):
		for name in (CUSTOMER,):
			if not frappe.db.exists("Customer", name):
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": name,
						"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
						"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
					}
				).insert()
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
				}
			).insert()

	# ------------------------------------------------------------------ helpers

	def capture(self, cheque_no, cheque_date=None, amount=100.0, party=CUSTOMER):
		cheque_no = f"{cheque_no}-{self.RUN}"
		cheque_date = cheque_date or nowdate()
		post_dated = frappe.utils.getdate(cheque_date) > frappe.utils.getdate(nowdate())

		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = COMPANY
		pe.posting_date = nowdate()
		pe.party_type = "Customer"
		pe.party = party
		pe.paid_from = self.receivable
		pe.paid_to = self.post_dated if post_dated else self.in_hand
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.reference_no = cheque_no
		pe.reference_date = cheque_date
		pe.custom_mfg_cheque_type = self.inbound_type
		pe.insert()
		pe.submit()
		return pe, frappe.db.get_value("Payment Entry", pe.name, "custom_mfg_cheque")

	def capture_outbound(self, cheque_no, amount=100.0):
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Pay"
		pe.company = COMPANY
		pe.posting_date = nowdate()
		pe.party_type = "Supplier"
		pe.party = SUPPLIER
		pe.paid_from = self.payable
		pe.paid_to = self.creditor
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.reference_no = f"{cheque_no}-{self.RUN}"
		pe.reference_date = nowdate()
		pe.custom_mfg_cheque_type = self.outbound_type
		pe.insert()
		pe.submit()
		return pe, frappe.db.get_value("Payment Entry", pe.name, "custom_mfg_cheque")

	def scoped_party(self, marker):
		"""A customer only this test writes to, so counting is deterministic."""
		name = f"_Test Cheque {marker}"
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				}
			).insert()
		return name

	def scope(self, party, **extra):
		"""Filters that see this test's cheques in this run and nothing else."""
		return {"company": COMPANY, "party": party, "search": self.RUN, **extra}

	def gl(self, voucher_type, voucher_no):
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)
		return {r.account: (flt(r.debit), flt(r.credit)) for r in rows}

	# -------------------------------------------------------------------- tests

	def test_capture_lands_in_cheques_in_hand(self):
		pe, cheque = self.capture("T-100")
		doc = frappe.get_doc("MFG Cheque", cheque)
		self.assertEqual(doc.status, "Received")
		self.assertEqual(doc.is_post_dated, 0)
		self.assertEqual(self.gl("Payment Entry", pe.name)[self.in_hand], (100.0, 0.0))

	def test_quick_entry_exposes_searchable_company_dimensions(self):
		meta = ops.get_quick_entry(COMPANY)
		cost_center = next(d for d in meta["dimensions"] if d["fieldname"] == "cost_center")
		self.assertEqual(cost_center["options"], "Cost Center")
		self.assertEqual(cost_center["filters"], {"company": COMPANY})

		results = cheque_api.search_link(
			"Cost Center", txt=self.cost_center, filters={"company": COMPANY}
		)
		self.assertIn(self.cost_center, [row["value"] for row in results])

	def test_quick_capture_dimensions_reach_every_accounting_entry(self):
		out = ops.create_cheque_capture(
			{
				"company": COMPANY,
				"cheque_type": self.inbound_type,
				"party_type": "Customer",
				"party": CUSTOMER,
				"amount": 100,
				"cheque_number": f"T-DIM-{self.RUN}",
				"cheque_date": nowdate(),
				"cost_center": self.cost_center,
			}
		)
		self.assertEqual(
			frappe.db.get_value("Payment Entry", out["payment_entry"], "cost_center"), self.cost_center
		)
		self.assertEqual(
			frappe.db.get_value(CHEQUE_DT, out["cheque"], "cost_center"), self.cost_center
		)
		capture_dimensions = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Payment Entry",
				"voucher_no": out["payment_entry"],
				"is_cancelled": 0,
			},
			pluck="cost_center",
		)
		self.assertTrue(capture_dimensions)
		self.assertEqual(set(capture_dimensions), {self.cost_center})

		deposit = ops.deposit(out["cheque"])
		deposit_dimensions = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Journal Entry",
				"voucher_no": deposit["journal_entry"],
				"is_cancelled": 0,
			},
			pluck="cost_center",
		)
		self.assertTrue(deposit_dimensions)
		self.assertEqual(set(deposit_dimensions), {self.cost_center})

	def test_quick_capture_can_clear_an_optional_dimension_default(self):
		settings = frappe.get_single("MFG Cheque Settings")
		row = next(r for r in settings.company_settings if r.company == COMPANY)
		row.cost_center = self.cost_center
		settings.save()

		out = ops.create_cheque_capture(
			{
				"company": COMPANY,
				"cheque_type": self.inbound_type,
				"party_type": "Customer",
				"party": CUSTOMER,
				"amount": 100,
				"cheque_number": f"T-NO-DIM-{self.RUN}",
				"cheque_date": nowdate(),
				"cost_center": "",
			}
		)
		self.assertFalse(frappe.db.get_value("Payment Entry", out["payment_entry"], "cost_center"))
		self.assertFalse(frappe.db.get_value(CHEQUE_DT, out["cheque"], "cost_center"))

	def test_captured_dimensions_are_immutable(self):
		_pe, cheque = self.capture("T-DIM-LOCK")
		doc = frappe.get_doc(CHEQUE_DT, cheque)
		doc.cost_center = self.cost_center
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_deposit_does_not_touch_the_bank(self):
		"""The whole point of the three-account model.

		A deposited cheque is with the bank for collection; the money is not ours
		until it clears, so the bank ledger must still tie to the statement.
		"""
		_pe, cheque = self.capture("T-101")
		out = ops.deposit(cheque)
		gl = self.gl("Journal Entry", out["journal_entry"])

		self.assertEqual(frappe.db.get_value("MFG Cheque", cheque, "status"), "Deposited")
		self.assertEqual(gl[self.transit], (100.0, 0.0))
		self.assertEqual(gl[self.in_hand], (0.0, 100.0))
		self.assertNotIn(self.bank, gl)

	def test_clear_debits_the_bank(self):
		_pe, cheque = self.capture("T-102")
		ops.deposit(cheque)
		out = ops.clear(cheque)
		gl = self.gl("Payment Entry", out["payment_entry"])

		self.assertEqual(frappe.db.get_value("MFG Cheque", cheque, "status"), "Cleared")
		self.assertEqual(gl[self.bank], (100.0, 0.0))
		self.assertEqual(gl[self.transit], (0.0, 100.0))

	def test_duplicate_deposit_is_refused(self):
		_pe, cheque = self.capture("T-103")
		ops.deposit(cheque)
		with self.assertRaises(frappe.ValidationError):
			ops.deposit(cheque)

	def test_bounce_reverses_the_deposit_and_restores_the_receivable(self):
		"""Atomic on purpose: a bounce that only reversed the deposit would leave
		the cheque relieved and the customer still looking paid."""
		_pe, cheque = self.capture("T-104")
		ops.deposit(cheque)
		out = ops.bounce(cheque, fee_amount=5.0, fee_treatment="Company Expense")

		doc = frappe.get_doc("MFG Cheque", cheque)
		self.assertEqual(doc.status, "Bounced")
		self.assertEqual(doc.deposit_reversal_method, "Cancellation")
		self.assertEqual(
			frappe.db.get_value("Journal Entry", doc.deposit_journal_entry, "docstatus"), 2
		)

		gl = self.gl("Journal Entry", out["journal_entry"])
		self.assertEqual(gl[self.receivable], (100.0, 0.0))
		self.assertEqual(gl[self.in_hand], (0.0, 100.0))

		fee_gl = self.gl("Journal Entry", out["fee_journal_entry"])
		self.assertEqual(fee_gl[self.charges], (5.0, 0.0))
		self.assertEqual(fee_gl[self.bank], (0.0, 5.0))

	def test_recharged_fee_hits_the_customer_not_the_expense(self):
		_pe, cheque = self.capture("T-105")
		ops.deposit(cheque)
		out = ops.bounce(cheque, fee_amount=7.0, fee_treatment="Recharge to Party")

		fee_gl = self.gl("Journal Entry", out["fee_journal_entry"])
		self.assertEqual(fee_gl[self.receivable], (7.0, 0.0))
		self.assertNotIn(self.charges, fee_gl)

	def test_return_to_party_posts_nothing(self):
		_pe, cheque = self.capture("T-106")
		ops.deposit(cheque)
		ops.bounce(cheque)
		before = frappe.db.count("GL Entry", {"company": COMPANY})

		ops.return_to_party(cheque, note="handed back")

		self.assertEqual(frappe.db.get_value("MFG Cheque", cheque, "status"), "Returned to Customer")
		self.assertEqual(frappe.db.count("GL Entry", {"company": COMPANY}), before)

	def test_replace_produces_a_draft_pointing_back(self):
		"""The replacement is captured like any other cheque, so an abandoned draft
		leaves the bounced cheque untouched."""
		_pe, cheque = self.capture("T-107")
		ops.deposit(cheque)
		ops.bounce(cheque)
		out = ops.replace(cheque)

		new_pe = frappe.get_doc("Payment Entry", out["payment_entry"])
		self.assertEqual(new_pe.docstatus, 0)
		self.assertEqual(new_pe.custom_mfg_replaces, cheque)
		self.assertEqual(new_pe.paid_from, self.receivable)
		self.assertEqual(new_pe.paid_to, self.in_hand)
		self.assertEqual(frappe.db.get_value("MFG Cheque", cheque, "status"), "Bounced")

	def test_cancelling_a_replacement_restores_the_original(self):
		_pe, cheque = self.capture("T-107-CANCEL")
		ops.deposit(cheque)
		ops.bounce(cheque)
		out = ops.replace(cheque)

		replacement = frappe.get_doc("Payment Entry", out["payment_entry"])
		replacement.reference_no = f"T-107-NEW-{self.RUN}"
		replacement.reference_date = nowdate()
		replacement.save()
		replacement.submit()
		self.assertEqual(frappe.db.get_value(CHEQUE_DT, cheque, "status"), "Replaced")

		replacement.cancel()
		self.assertEqual(frappe.db.get_value(CHEQUE_DT, cheque, "status"), "Bounced")
		self.assertFalse(frappe.db.get_value(CHEQUE_DT, cheque, "replaced_by"))

	def test_auto_maturity_setting_is_respected(self):
		with (
			patch.object(ops, "get_settings", return_value=frappe._dict(auto_mature_post_dated=0)),
			patch.object(frappe, "get_all") as get_all,
		):
			ops.mature_post_dated_cheques()
		get_all.assert_not_called()

	def test_post_dated_is_held_then_matured(self):
		_pe, cheque = self.capture("T-108", cheque_date=add_days(nowdate(), 30))
		doc = frappe.get_doc("MFG Cheque", cheque)
		self.assertEqual(doc.status, "Post-Dated Held")
		self.assertEqual(doc.is_post_dated, 1)

		out = ops.mature(cheque)
		gl = self.gl("Journal Entry", out["journal_entry"])
		self.assertEqual(frappe.db.get_value("MFG Cheque", cheque, "status"), "Received")
		self.assertEqual(gl[self.in_hand], (100.0, 0.0))
		self.assertEqual(gl[self.post_dated], (0.0, 100.0))

	def test_maturity_uses_today_when_the_cheque_date_is_closed(self):
		_pe, cheque = self.capture("T-108-CLOSED", cheque_date=add_days(nowdate(), 30))
		with patch.object(ops, "_posting_blocked", side_effect=["closed", None]):
			out = ops.mature(cheque)

		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		self.assertEqual(str(je.posting_date), nowdate())
		self.assertIn("closed", je.user_remark)

	def test_clear_before_deposit_is_refused(self):
		_pe, cheque = self.capture("T-109")
		with self.assertRaises(frappe.ValidationError):
			ops.clear(cheque)

	def test_clear_refuses_a_non_bank_override(self):
		_pe, cheque = self.capture("T-109-NONBANK")
		ops.deposit(cheque)
		with self.assertRaises(frappe.ValidationError):
			ops.clear(cheque, bank_account=self.in_hand)

	def test_manual_creation_is_blocked(self):
		"""A cheque with no Payment Entry behind it has no GL behind it."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "MFG Cheque",
					"company": COMPANY,
					"cheque_number": "T-BY-HAND",
					"status": "Received",
				}
				).insert()

	def test_captured_cheque_cannot_be_deleted_directly(self):
		_pe, cheque = self.capture("T-NO-DELETE")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(CHEQUE_DT, cheque)

	def test_outbound_bounce_fee_is_forced_to_company_expense(self):
		_pe, cheque = self.capture_outbound("T-OUT-FEE")
		out = ops.bounce(cheque, fee_amount=6.0, fee_treatment="Recharge to Party")

		doc = frappe.get_doc(CHEQUE_DT, cheque)
		self.assertEqual(doc.status, "Bounced")
		self.assertEqual(doc.fee_treatment, "Company Expense")
		fee_gl = self.gl("Journal Entry", out["fee_journal_entry"])
		self.assertEqual(fee_gl[self.charges], (6.0, 0.0))
		self.assertNotIn(self.creditor, fee_gl)

	def test_duplicate_number_for_same_customer_is_refused(self):
		self.capture("T-110")
		with self.assertRaises(frappe.ValidationError):
			self.capture("T-110")

	def test_same_number_for_a_different_customer_is_allowed(self):
		"""Cheque numbers repeat across drawers. A site-wide unique index would
		make this a support ticket."""
		other = "_Test Cheque Customer 2"
		if not frappe.db.exists("Customer", other):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": other,
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				}
			).insert()

		self.capture("T-111")
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = COMPANY
		pe.posting_date = nowdate()
		pe.party_type = "Customer"
		pe.party = other
		pe.paid_from = self.receivable
		pe.paid_to = self.in_hand
		pe.paid_amount = 100.0
		pe.received_amount = 100.0
		pe.reference_no = "T-111"
		pe.reference_date = nowdate()
		pe.custom_mfg_cheque_type = self.inbound_type
		pe.insert()
		pe.submit()

		self.assertTrue(frappe.db.get_value("Payment Entry", pe.name, "custom_mfg_cheque"))

	def test_capture_cannot_be_cancelled_once_downstream_entries_exist(self):
		pe, cheque = self.capture("T-112")
		ops.deposit(cheque)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Payment Entry", pe.name).cancel()

	def test_bank_cash_clearing_account_is_refused(self):
		"""Typing a clearing account Bank would offer it up in Bank Clearance and
		present a piece of paper as cash."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "MFG Cheque Type",
					"cheque_type_name": f"Bad Type - {ABBR}",
					"company": COMPANY,
					"direction": "Inbound",
					"clearing_account": self.bank,
					"transit_account": self.transit,
				}
			).insert()

	# ------------------------------------------------------- dashboard & filters

	def test_dashboard_counts_by_state_and_bucket(self):
		party = self.scoped_party("Tiles")
		self.capture("T-200", party=party)  # Received -> in hand
		_pe, deposited = self.capture("T-201", party=party)
		ops.deposit(deposited)
		self.capture("T-202", cheque_date=add_days(nowdate(), 45), party=party)

		data = ops.get_cheque_dashboard(filters=self.scope(party))
		kpis = data["kpis"]

		self.assertEqual(kpis["in_hand"]["count"], 1)
		self.assertEqual(kpis["under_collection"]["count"], 1)
		self.assertEqual(kpis["post_dated"]["count"], 1)
		self.assertEqual(kpis["outstanding"]["count"], 3)
		self.assertEqual(kpis["outstanding"]["amount"], 300.0)

		buckets = {b["label"]: b for b in data["buckets"]}
		self.assertEqual(buckets["Due in 7 days"]["count"], 2)
		self.assertEqual(buckets["Due in 90 days"]["count"], 1)

	def test_dashboard_ignores_settled_cheques(self):
		"""A cleared cheque is history, not money in flight."""
		party = self.scoped_party("Settled")
		_pe, cheque = self.capture("T-203", party=party)
		ops.deposit(cheque)
		ops.clear(cheque)

		kpis = ops.get_cheque_dashboard(filters=self.scope(party))["kpis"]
		self.assertEqual(kpis["outstanding"]["count"], 0)

	def test_amount_range_filter_uses_both_bounds(self):
		"""Both bounds must survive: a dict filter can only hold one per field."""
		party = self.scoped_party("Range")
		self.capture("T-204", amount=50.0, party=party)
		self.capture("T-205", amount=500.0, party=party)
		self.capture("T-206", amount=5000.0, party=party)

		result = ops.get_cheques(filters=self.scope(party, min_amount=100, max_amount=1000))
		numbers = [r["cheque_number"] for r in result["rows"]]

		self.assertEqual(numbers, [f"T-205-{self.RUN}"])
		self.assertEqual(result["total"], 1)

	def test_search_matches_number_and_party(self):
		self.capture("T-FINDME")
		self.assertEqual(ops.get_cheques(filters={"search": f"FINDME-{self.RUN}"})["total"], 1)
		self.assertGreaterEqual(ops.get_cheques(filters={"search": "Cheque Customer"})["total"], 1)

	def test_overdue_filter_is_deposited_and_past_due(self):
		"""Overdue means presented and past its date - not merely old."""
		party = self.scoped_party("Overdue")
		_pe, old_cleared = self.capture("T-207", cheque_date=add_days(nowdate(), -30), party=party)
		ops.deposit(old_cleared)
		ops.clear(old_cleared)

		_pe, overdue = self.capture("T-208", cheque_date=add_days(nowdate(), -30), party=party)
		ops.deposit(overdue)

		rows = ops.get_cheques(filters=self.scope(party, overdue=1))["rows"]
		self.assertEqual([r["cheque_number"] for r in rows], [f"T-208-{self.RUN}"])

	def test_bulk_deposit_reports_each_failure_separately(self):
		"""One bad cheque must not take the batch down with it."""
		_pe, good = self.capture("T-209")
		_pe, already = self.capture("T-210")
		ops.deposit(already)

		result = ops.bulk_deposit([good, already])

		self.assertEqual(len(result["deposited"]), 1)
		self.assertEqual(len(result["failed"]), 1)
		self.assertEqual(result["failed"][0]["cheque"], already)
		self.assertEqual(frappe.db.get_value(CHEQUE_DT, good, "status"), "Deposited")

	def test_list_pagination_reports_the_full_total(self):
		party = self.scoped_party("Paging")
		for i in range(3):
			self.capture(f"T-30{i}", party=party)
		page = ops.get_cheques(filters=self.scope(party), limit=2, start=0)
		self.assertEqual(len(page["rows"]), 2)
		self.assertEqual(page["total"], 3)

	# ------------------------------------------------------------- quick entry

	def test_quick_capture_creates_a_real_payment_entry(self):
		"""The dialog is a shortcut through the desk form, not around it."""
		import json as _json

		result = ops.create_cheque_capture(
			_json.dumps(
				{
					"company": COMPANY,
					"cheque_type": self.inbound_type,
					"party_type": "Customer",
					"party": CUSTOMER,
					"amount": 250.0,
					"cheque_number": f"QE-1-{self.RUN}",
					"cheque_date": nowdate(),
				}
			)
		)

		self.assertTrue(result["cheque"])
		self.assertEqual(result["status"], "Received")
		pe = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(pe.paid_to, self.in_hand)
		self.assertEqual(self.gl("Payment Entry", pe.name)[self.in_hand], (250.0, 0.0))

	def test_quick_capture_still_obeys_the_desk_validations(self):
		"""Reachable directly, so it cannot be the soft way in."""
		import json as _json

		payload = {
			"company": COMPANY,
			"cheque_type": self.inbound_type,
			"party_type": "Customer",
			"party": CUSTOMER,
			"amount": 100.0,
			"cheque_number": f"QE-2-{self.RUN}",
			"cheque_date": nowdate(),
		}
		ops.create_cheque_capture(_json.dumps(payload))

		# Same number, same customer.
		with self.assertRaises(frappe.ValidationError):
			ops.create_cheque_capture(_json.dumps(payload))

		# And an incomplete payload names what is missing rather than crashing.
		with self.assertRaises(frappe.ValidationError):
			ops.create_cheque_capture(_json.dumps({"company": COMPANY}))

	def test_quick_capture_routes_a_post_dated_cheque_to_its_own_account(self):
		import json as _json

		result = ops.create_cheque_capture(
			_json.dumps(
				{
					"company": COMPANY,
					"cheque_type": self.inbound_type,
					"party_type": "Customer",
					"party": CUSTOMER,
					"amount": 300.0,
					"cheque_number": f"QE-3-{self.RUN}",
					"cheque_date": add_days(nowdate(), 30),
				}
			)
		)

		self.assertEqual(result["status"], "Post-Dated Held")
		gl = self.gl("Payment Entry", result["payment_entry"])
		self.assertEqual(gl[self.post_dated], (300.0, 0.0))
		self.assertNotIn(self.in_hand, gl)

	def test_allowed_actions_matches_the_state_machine(self):
		"""The SPA renders buttons from this, so it cannot offer what the server
		would reject."""
		self.assertEqual(ops.allowed_actions("Received", "Inbound"), ["deposit"])
		self.assertEqual(ops.allowed_actions("Deposited", "Inbound"), ["clear", "bounce"])
		self.assertEqual(ops.allowed_actions("Cleared", "Inbound"), [])
		self.assertEqual(ops.allowed_actions("Issued", "Outbound"), ["clear", "bounce"])

	# ---------------------------------------------------------- CFO reporting

	def test_register_and_position_use_company_currency_amounts(self):
		party = self.scoped_party("Report Position")
		self.capture("T-REPORT-POS", amount=125.0, party=party)
		filters = {"company": COMPANY, "customer": party}

		_columns, register, _message, _chart, summary = reporting.execute_report(
			"Cheque Register", filters
		)
		self.assertEqual(len(register), 1)
		self.assertEqual(register[0].base_amount, 125.0)
		self.assertEqual(summary[1]["value"], 125.0)

		_columns, position, _message, _chart, summary = reporting.execute_report(
			"Cheque Position", filters
		)
		received = next(row for row in position if row.status == "Received")
		self.assertEqual(received.amount, 125.0)
		self.assertEqual(summary[0]["value"], 125.0)

	def test_cash_flow_kpi_matches_forecast_report(self):
		party = self.scoped_party("Report Forecast")
		self.capture("T-REPORT-FLOW", cheque_date=add_days(nowdate(), 5), amount=210.0, party=party)
		filters = {"company": COMPANY, "customer": party, "forecast_days": 7}

		_columns, data, _message, _chart, summary = reporting.execute_report(
			"Cheque Cash Flow Forecast", filters
		)
		self.assertEqual(sum(row.expected_inflow for row in data), 210.0)
		self.assertEqual(summary[0]["value"], 210.0)
		card = cfo_dashboard.get_number_card({**filters, "metric": "expected_inflow"})
		self.assertEqual(card["value"], summary[0]["value"])
		self.assertEqual(card["route"], ["query-report", "Cheque Cash Flow Forecast"])

	def test_cfo_endpoints_enforce_management_roles(self):
		with patch("frappe.only_for") as only_for:
			cfo_dashboard.get_number_card({"metric": "total_exposure", "company": COMPANY})
			only_for.assert_called_once_with(cfo_dashboard.MANAGEMENT_ROLES)

		with patch("frappe.only_for") as only_for:
			with patch("cheque_management.cfo_dashboard._get_cheques", return_value=[]):
				cfo_dashboard.get_alerts({"company": COMPANY})
			only_for.assert_called_once_with(cfo_dashboard.MANAGEMENT_ROLES)

	def test_cfo_workspace_has_routable_title(self):
		workspace = frappe.get_doc("Workspace", "CFO Cheque Management")
		self.assertEqual(workspace.title, workspace.name)
		self.assertTrue(frappe.db.exists("Dashboard", "CFO Cheque Management Dashboard"))

		content = json.loads(workspace.content)
		block_references = (
			("chart", "chart_name", workspace.charts),
			("number_card", "number_card_name", workspace.number_cards),
			("shortcut", "shortcut_name", workspace.shortcuts),
		)
		for block_type, fieldname, rows in block_references:
			referenced_labels = {
				block["data"][fieldname] for block in content if block["type"] == block_type
			}
			self.assertSetEqual(referenced_labels, {row.label for row in rows})

	def test_reconciliation_matches_open_cheque_to_configured_gl(self):
		party = self.scoped_party("Report Reconciliation")
		self.capture("T-REPORT-RECON", amount=175.0, party=party)
		_columns, data, _message, _chart, _summary = reporting.execute_report(
			"Cheque Accounting Reconciliation", {"company": COMPANY, "to_date": nowdate()}
		)
		in_hand = next(row for row in data if row.account == self.in_hand)
		self.assertEqual(in_hand.gl_balance, in_hand.cheque_management_balance)
		self.assertEqual(in_hand.status, "Reconciled")

	def test_bounced_analysis_and_alerts_use_historical_bounce_marker(self):
		party = self.scoped_party("Report Bounce")
		_pe, cheque = self.capture("T-REPORT-BOUNCE", amount=95.0, party=party)
		ops.deposit(cheque)
		ops.bounce(cheque, reason="Reporting test")
		filters = {"company": COMPANY, "customer": party, "group_by": "Customer"}

		_columns, data, _message, _chart, summary = reporting.execute_report(
			"Bounced Cheque Analysis", filters
		)
		self.assertEqual(data[0].cheque_count, 1)
		self.assertEqual(data[0].bounced_amount, 95.0)
		self.assertEqual(summary[0]["value"], 1)
		alerts = cfo_dashboard.get_alerts(filters)
		self.assertTrue(any(alert["key"] == "bounced" for alert in alerts))

	def test_all_report_entrypoints_execute(self):
		party = self.scoped_party("Report Smoke")
		self.capture("T-REPORT-SMOKE", amount=80.0, party=party)
		filters = {"company": COMPANY, "customer": party, "to_date": nowdate()}
		reports = (
			"Cheque Register",
			"Received Cheques",
			"Deposited Pending Clearance",
			"Bounced Cheques",
			"Customer Cheque Report",
			"Supplier Cheque Report",
			"Cheques Due Maturity",
			"Cheque Position",
			"Cheque Aging",
			"Cheque Cash Flow Forecast",
			"Cheques by Bank",
			"Bounced Cheque Analysis",
			"Customer Cheque Exposure",
			"Supplier Cheque Exposure",
			"Bank Reconciliation Cheque View",
			"Cheque Accounting Reconciliation",
			"Cheque Audit Trail",
			"Cancelled Cheques",
		)
		for report in reports:
			with self.subTest(report=report):
				columns, rows, _message, _chart, _summary = reporting.execute_report(report, filters)
				self.assertTrue(columns)
				self.assertIsInstance(rows, list)
