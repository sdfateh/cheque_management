# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Permission-aware reporting primitives for the cheque subledger.

`MFG Cheque` is the operational source. General Ledger is queried only for
accounting balances and is never mutated by this module.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import frappe
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from cheque_management.cheque_operations import dimension_fieldnames
from cheque_management.i18n import _

CHEQUE = "MFG Cheque"
CHEQUE_TYPE = "MFG Cheque Type"

INBOUND_LIVE = ("Post-Dated Held", "Received", "Deposited")
OUTBOUND_LIVE = ("Post-Dated Held", "Issued")
LIVE_STATUSES = (*INBOUND_LIVE, *OUTBOUND_LIVE)
TERMINAL_STATUSES = ("Cleared", "Bounced", "Returned to Customer", "Replaced", "Cancelled")
DEFAULT_DETAIL_LIMIT = 500
MAX_DETAIL_LIMIT = 5000

DETAIL_FIELDS = [
	"name",
	"company",
	"cheque_number",
	"cheque_type",
	"direction",
	"party_type",
	"party",
	"amount",
	"currency",
	"base_amount",
	"bank_account",
	"drawee_bank",
	"cheque_date",
	"status",
	"source_payment_entry",
	"maturity_journal_entry",
	"deposit_journal_entry",
	"deposit_reversal_journal_entry",
	"clear_payment_entry",
	"bounce_journal_entry",
	"bounce_fee_journal_entry",
	"bounce_date",
	"bounce_reason",
	"returned_on",
	"replaces",
	"replaced_by",
	"creation",
	"modified",
	"owner",
	"modified_by",
]


def execute_report(report_name, filters=None):
	filters = _filters(filters)
	_check_cheque_permission()
	executors = {
		"Cheque Register": _cheque_register,
		"Received Cheques": _received_cheques,
		"Deposited Pending Clearance": _deposited_pending,
		"Bounced Cheques": _bounced_cheques,
		"Customer Cheque Report": _customer_cheque_report,
		"Supplier Cheque Report": _supplier_cheque_report,
		"Cheques Due Maturity": _cheques_due,
		"Cheque Position": _cheque_position,
		"Cheque Aging": _cheque_aging,
		"Cheque Cash Flow Forecast": _cash_flow_forecast,
		"Cheques by Bank": _cheques_by_bank,
		"Bounced Cheque Analysis": _bounced_analysis,
		"Customer Cheque Exposure": _customer_exposure,
		"Supplier Cheque Exposure": _supplier_exposure,
		"Bank Reconciliation Cheque View": _bank_reconciliation,
		"Cheque Accounting Reconciliation": _accounting_reconciliation,
		"Cheque Audit Trail": _audit_trail,
		"Cancelled Cheques": _cancelled_cheques,
	}
	if report_name not in executors:
		frappe.throw(_("Unknown cheque report: {0}").format(report_name))
	result = executors[report_name](filters)
	return _normalize_result(result)


def _normalize_result(result):
	if len(result) == 2:
		columns, data = result
		return columns, data, None, None, None
	if len(result) == 3:
		columns, data, summary = result
		return columns, data, None, None, summary
	return result


def _filters(filters):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else filters
	return frappe._dict(filters or {})


def _check_cheque_permission():
	if not frappe.has_permission(CHEQUE, "read"):
		frappe.throw(_("You are not permitted to read cheque reports."), frappe.PermissionError)


def _check_gl_permission():
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("General Ledger permission is required for this report."), frappe.PermissionError)


def _col(label, fieldname, fieldtype="Data", options=None, width=120):
	column = {
		"label": _(label),
		"fieldname": fieldname,
		"fieldtype": fieldtype,
		"width": width,
	}
	if options:
		column["options"] = options
	return column


def _currency_column(label, fieldname="base_amount", width=140):
	return _col(label, fieldname, "Currency", "Company:company:default_currency", width)


def _base_db_filters(filters, statuses=None, direction=None):
	db_filters = {"docstatus": ["<", 2]}
	for key in ("company", "cheque_type", "direction", "party_type", "bank_account", "status", "currency"):
		if filters.get(key):
			db_filters[key] = filters[key]
	if direction:
		db_filters["direction"] = direction
	if statuses:
		db_filters["status"] = ["in", list(statuses)]
	if filters.customer:
		db_filters.update({"party_type": "Customer", "party": filters.customer})
	if filters.supplier:
		db_filters.update({"party_type": "Supplier", "party": filters.supplier})
	if filters.cheque_date:
		db_filters["cheque_date"] = filters.cheque_date
	elif filters.due_date:
		db_filters["cheque_date"] = filters.due_date
	else:
		if filters.from_date and filters.to_date:
			db_filters["cheque_date"] = ["between", [filters.from_date, filters.to_date]]
		elif filters.from_date:
			db_filters["cheque_date"] = [">=", filters.from_date]
		elif filters.to_date:
			db_filters["cheque_date"] = ["<=", filters.to_date]
	for dimension in dimension_fieldnames():
		if filters.get(dimension) and frappe.get_meta(CHEQUE).has_field(dimension):
			db_filters[dimension] = ["in", _as_list(filters.get(dimension))]
	return db_filters


def _as_list(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return list(value)
	return [value]


def _get_cheques(
	filters, statuses=None, direction=None, unlimited=False, order_by="cheque_date asc", extra_filters=None
):
	fields = list(DETAIL_FIELDS)
	meta = frappe.get_meta(CHEQUE)
	for optional in ("cancelled_from_status", "cancellation_date", "cancelled_by", "cancellation_reason"):
		if meta.has_field(optional):
			fields.append(optional)
	for dimension in dimension_fieldnames():
		if meta.has_field(dimension) and dimension not in fields:
			fields.append(dimension)
	limit = 0 if unlimited else min(max(cint(filters.limit) or DEFAULT_DETAIL_LIMIT, 1), MAX_DETAIL_LIMIT)
	db_filters = _base_db_filters(filters, statuses=statuses, direction=direction)
	if extra_filters:
		db_filters.update(extra_filters)
	rows = frappe.get_list(
		CHEQUE,
		fields=fields,
		filters=db_filters,
		order_by=order_by,
		limit_page_length=limit,
	)
	_hydrate_rows(rows)
	return rows


def _hydrate_rows(rows):
	if not rows:
		return
	party_names = {}
	for party_type, title_field in (("Customer", "customer_name"), ("Supplier", "supplier_name")):
		names = list({row.party for row in rows if row.party_type == party_type and row.party})
		if names:
			for item in frappe.get_all(
				party_type, filters={"name": ["in", names]}, fields=["name", title_field]
			):
				party_names[(party_type, item.name)] = item.get(title_field)

	pe_names = list(
		{name for row in rows for name in (row.source_payment_entry, row.clear_payment_entry) if name}
	)
	je_names = list(
		{
			name
			for row in rows
			for name in (
				row.maturity_journal_entry,
				row.deposit_journal_entry,
				row.deposit_reversal_journal_entry,
				row.bounce_journal_entry,
				row.bounce_fee_journal_entry,
			)
			if name
		}
	)
	pe_meta = _document_metadata("Payment Entry", pe_names)
	je_meta = _document_metadata("Journal Entry", je_names)

	parents = [row.name for row in rows]
	allocations = defaultdict(list)
	if parents:
		for item in frappe.get_all(
			"MFG Cheque Allocation",
			filters={"parent": ["in", parents]},
			fields=["parent", "reference_doctype", "reference_name", "allocated_amount"],
			order_by="idx asc",
		):
			allocations[item.parent].append(item)

	for row in rows:
		row.party_name = party_names.get((row.party_type, row.party), row.party)
		row.due_date = row.cheque_date
		row.source_posting_date = (pe_meta.get(row.source_payment_entry) or {}).get("posting_date")
		row.deposit_date = (je_meta.get(row.deposit_journal_entry) or {}).get("posting_date")
		row.clear_date = (pe_meta.get(row.clear_payment_entry) or {}).get("posting_date")
		row.source_invoice = ", ".join(a.reference_name for a in allocations.get(row.name, []))
		row._allocations = allocations.get(row.name, [])
		row.days_outstanding = max(date_diff(nowdate(), row.source_posting_date or row.cheque_date), 0)
		row.days_to_due_date = date_diff(row.cheque_date, nowdate())
		row.days_since_deposit = max(date_diff(nowdate(), row.deposit_date), 0) if row.deposit_date else None
		row.accounting_dimensions = ", ".join(
			f"{dimension}: {row.get(dimension)}" for dimension in dimension_fieldnames() if row.get(dimension)
		)


def _document_metadata(doctype, names):
	if not names:
		return {}
	fields = ["name", "posting_date", "modified", "modified_by", "docstatus"]
	if frappe.get_meta(doctype).has_field("clearance_date"):
		fields.append("clearance_date")
	return {row.name: row for row in frappe.get_all(doctype, filters={"name": ["in", names]}, fields=fields)}


def _register_columns():
	return [
		_col("Cheque", "name", "Link", CHEQUE, 130),
		_col("Cheque Number", "cheque_number", width=130),
		_col("Cheque Type", "cheque_type", "Link", CHEQUE_TYPE, 150),
		_col("Direction", "direction", width=90),
		_col("Party Type", "party_type", width=100),
		_col("Party", "party", "Dynamic Link", "party_type", 140),
		_col("Party Name", "party_name", width=160),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Currency", "currency", "Link", "Currency", 80),
		_currency_column("Company Currency Amount"),
		_col("Bank Account", "bank_account", "Link", "Account", 180),
		_col("Cheque Date", "cheque_date", "Date", width=100),
		_col("Due Date", "due_date", "Date", width=100),
		_col("Status", "status", width=130),
		_col("Source Invoice", "source_invoice", width=150),
		_col("Source Payment Entry", "source_payment_entry", "Link", "Payment Entry", 150),
		_col("Deposit Journal Entry", "deposit_journal_entry", "Link", "Journal Entry", 150),
		_col("Clear Payment Entry", "clear_payment_entry", "Link", "Payment Entry", 150),
		_col("Bounce Journal Entry", "bounce_journal_entry", "Link", "Journal Entry", 150),
		_col("Days Outstanding", "days_outstanding", "Int", width=100),
		_col("Accounting Dimensions", "accounting_dimensions", width=200),
	]


def _cheque_register(filters):
	rows = _get_cheques(filters)
	return _register_columns(), rows, _amount_summary(rows, _("Cheques"), _("Total Amount"))


def _received_cheques(filters):
	rows = _get_cheques(filters, statuses=("Received", "Post-Dated Held"), direction="Inbound")
	columns = [
		_col("Cheque", "name", "Link", CHEQUE),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Customer", "party", "Link", "Customer", 150),
		_col("Party Name", "party_name", width=160),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Currency", "currency", "Link", "Currency", 80),
		_col("Cheque Date", "cheque_date", "Date"),
		_col("Due Date", "due_date", "Date"),
		_col("Bank", "drawee_bank", width=140),
		_col("Status", "status", width=130),
		_col("Days to Due Date", "days_to_due_date", "Int"),
		_col("Source Invoice", "source_invoice", width=150),
		_col("Source Payment Entry", "source_payment_entry", "Link", "Payment Entry", 150),
	]
	return columns, rows, _amount_summary(rows, _("Open Inbound Cheques"), _("Open Inbound Amount"))


def _deposited_pending(filters):
	rows = _get_cheques(filters, statuses=("Deposited",), direction="Inbound")
	thresholds = _aging_thresholds(filters, defaults=(2, 5, 10))
	for row in rows:
		row.clearance_aging = _bucket(
			row.days_since_deposit or 0, thresholds, ("0–2 Days", "3–5 Days", "6–10 Days", "> 10 Days")
		)
	columns = [
		_col("Cheque", "name", "Link", CHEQUE),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Customer", "party", "Dynamic Link", "party_type", 150),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Bank Account", "bank_account", "Link", "Account", 180),
		_col("Deposit Date", "deposit_date", "Date"),
		_col("Days Since Deposit", "days_since_deposit", "Int"),
		_col("Aging Indicator", "clearance_aging", width=110),
		_col("Deposit Journal Entry", "deposit_journal_entry", "Link", "Journal Entry", 160),
		_col("Status", "status"),
	]
	return columns, rows, _amount_summary(rows, _("Pending Clearance"), _("Pending Amount"))


def _bounced_cheques(filters):
	rows = _get_cheques(
		filters,
		order_by="bounce_date desc, cheque_date desc",
		extra_filters={"bounce_journal_entry": ["is", "set"]},
	)
	for row in rows:
		row.outstanding_amount = _allocation_outstanding(row)
	columns = [
		_col("Cheque", "name", "Link", CHEQUE),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Party", "party", "Dynamic Link", "party_type", 150),
		_col("Party Type", "party_type"),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Currency", "currency", "Link", "Currency", 80),
		_col("Cheque Date", "cheque_date", "Date"),
		_col("Deposit Date", "deposit_date", "Date"),
		_col("Bounce Date", "bounce_date", "Date"),
		_col("Bank", "bank_account", "Link", "Account", 180),
		_col("Bounce Reason", "bounce_reason", width=220),
		_col("Current Status", "status", width=130),
		_col("Payment Entry", "source_payment_entry", "Link", "Payment Entry", 150),
		_col("Journal Entry", "bounce_journal_entry", "Link", "Journal Entry", 150),
		_col("Outstanding Amount", "outstanding_amount", "Currency", "currency", 140),
		_col("Days Outstanding", "days_outstanding", "Int"),
	]
	all_rows = _get_cheques(filters, unlimited=True)
	bounced_total = sum(flt(row.base_amount) for row in rows)
	rate = (len(rows) / len(all_rows) * 100) if all_rows else 0
	summary = [
		_summary(_("Bounced Cheques"), len(rows), "Int", "Red"),
		_summary(_("Bounced Amount"), bounced_total, "Currency", "Red", _company_currency(filters)),
		_summary(_("Bounce Rate"), rate, "Percent", "Orange"),
	]
	return columns, rows, summary


def _allocation_outstanding(row):
	if not row._allocations:
		return flt(row.amount)
	total = 0.0
	for allocation in row._allocations:
		if not frappe.db.exists("DocType", allocation.reference_doctype):
			continue
		outstanding = frappe.db.get_value(
			allocation.reference_doctype, allocation.reference_name, "outstanding_amount"
		)
		total += min(abs(flt(outstanding)), abs(flt(allocation.allocated_amount)))
	return total


def _party_status_report(filters, party_type):
	direction = "Inbound" if party_type == "Customer" else "Outbound"
	rows = _get_cheques(filters, direction=direction, unlimited=True)
	groups = {}
	for row in rows:
		item = groups.setdefault(
			row.party,
			frappe._dict(
				party=row.party,
				party_name=row.party_name,
				company=row.company,
				received=0.0,
				issued=0.0,
				post_dated=0.0,
				deposited=0.0,
				cleared=0.0,
				bounced=0.0,
				outstanding=0.0,
				total_exposure=0.0,
			),
		)
		amount = flt(row.base_amount)
		field = {
			"Received": "received",
			"Issued": "issued",
			"Post-Dated Held": "post_dated",
			"Deposited": "deposited",
			"Cleared": "cleared",
			"Bounced": "bounced",
		}.get(row.status)
		if field:
			item[field] += amount
		if row.status in (INBOUND_LIVE if direction == "Inbound" else OUTBOUND_LIVE):
			item.outstanding += amount
			item.total_exposure += amount
	return sorted(groups.values(), key=lambda row: row.total_exposure, reverse=True)


def _customer_cheque_report(filters):
	rows = _party_status_report(filters, "Customer")
	columns = _party_columns("Customer", include_deposited=True)
	return columns, rows, _group_summary(rows)


def _supplier_cheque_report(filters):
	rows = _party_status_report(filters, "Supplier")
	columns = _party_columns("Supplier", include_deposited=False)
	return columns, rows, _group_summary(rows)


def _party_columns(party_type, include_deposited):
	columns = [
		_col(party_type, "party", "Link", party_type, 160),
		_col("Party Name", "party_name", width=180),
	]
	if party_type == "Customer":
		columns.append(_currency_column("Received", "received"))
	else:
		columns.append(_currency_column("Issued", "issued"))
	columns.append(_currency_column("Post-Dated", "post_dated"))
	if include_deposited:
		columns.append(_currency_column("Deposited", "deposited"))
	columns.extend(
		[
			_currency_column("Cleared", "cleared"),
			_currency_column("Bounced", "bounced"),
			_currency_column("Outstanding Cheques", "outstanding", 150),
			_currency_column("Total Exposure", "total_exposure", 150),
		]
	)
	return columns


def _cheques_due(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	group_by = filters.group_by or "Party"
	groups = {}
	for row in rows:
		days = date_diff(row.cheque_date, nowdate())
		bucket = _maturity_bucket(days)
		group = _group_value(row, group_by)
		if group is None:
			continue
		key = (group, bucket, row.company)
		item = groups.setdefault(
			key,
			frappe._dict(
				group=group, maturity_bucket=bucket, company=row.company, cheque_count=0, amount=0.0
			),
		)
		item.cheque_count += 1
		item.amount += flt(row.base_amount)
	data = sorted(groups.values(), key=lambda row: (_maturity_order(row.maturity_bucket), row.group or ""))
	columns = [
		_col("Group", "group", width=180),
		_col("Maturity Bucket", "maturity_bucket", width=150),
		_col("Number of Cheques", "cheque_count", "Int"),
		_currency_column("Amount", "amount"),
	]
	return columns, data, _group_summary(data, amount_field="amount", count_field="cheque_count")


def _maturity_bucket(days):
	if days < 0:
		return _("Overdue")
	if days == 0:
		return _("Due Today")
	if days <= 7:
		return _("Due in 1–7 Days")
	if days <= 30:
		return _("Due in 8–30 Days")
	if days <= 60:
		return _("Due in 31–60 Days")
	if days <= 90:
		return _("Due in 61–90 Days")
	return _("Over 90 Days")


def _maturity_order(bucket):
	labels = [
		_("Overdue"),
		_("Due Today"),
		_("Due in 1–7 Days"),
		_("Due in 8–30 Days"),
		_("Due in 31–60 Days"),
		_("Due in 61–90 Days"),
		_("Over 90 Days"),
	]
	return labels.index(bucket) if bucket in labels else 99


def _cheque_position(filters):
	rows = _get_cheques(filters, unlimited=True)
	groups = {}
	for row in rows:
		key = (row.direction, row.status, row.company)
		item = groups.setdefault(
			key,
			frappe._dict(
				direction=row.direction, status=row.status, company=row.company, cheque_count=0, amount=0.0
			),
		)
		item.cheque_count += 1
		item.amount += flt(row.base_amount)
	totals = defaultdict(float)
	for row in groups.values():
		totals[row.direction] += row.amount
	for row in groups.values():
		row.percentage = row.amount / totals[row.direction] * 100 if totals[row.direction] else 0
	data = sorted(groups.values(), key=lambda row: (row.direction, row.status))
	inbound = sum(
		flt(row.base_amount) for row in rows if row.direction == "Inbound" and row.status in INBOUND_LIVE
	)
	outbound = sum(
		flt(row.base_amount) for row in rows if row.direction == "Outbound" and row.status in OUTBOUND_LIVE
	)
	columns = [
		_col("Direction", "direction"),
		_col("Status", "status", width=140),
		_col("Number of Cheques", "cheque_count", "Int"),
		_currency_column("Amount", "amount"),
		_col("Percentage", "percentage", "Percent"),
	]
	summary = [
		_summary(_("Inbound Position"), inbound, "Currency", "Green", _company_currency(filters)),
		_summary(_("Outbound Position"), outbound, "Currency", "Orange", _company_currency(filters)),
		_summary(
			_("Net Cheque Position"), inbound - outbound, "Currency", "Blue", _company_currency(filters)
		),
	]
	return columns, data, summary


def _cheque_aging(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	groups = {}
	for row in rows:
		age = max(date_diff(nowdate(), row.source_posting_date or row.cheque_date), 0)
		bucket = _bucket(
			age, (7, 30, 60, 90), ("0–7 Days", "8–30 Days", "31–60 Days", "61–90 Days", "> 90 Days")
		)
		group = _group_value(row, filters.group_by or "Party")
		if group is None:
			continue
		key = (group, bucket, row.company)
		item = groups.setdefault(
			key,
			frappe._dict(group=group, aging_bucket=bucket, company=row.company, cheque_count=0, amount=0.0),
		)
		item.cheque_count += 1
		item.amount += flt(row.base_amount)
	data = sorted(groups.values(), key=lambda row: (row.group or "", row.aging_bucket))
	columns = [
		_col("Group", "group", width=180),
		_col("Aging Bucket", "aging_bucket", width=130),
		_col("Number of Cheques", "cheque_count", "Int"),
		_currency_column("Amount", "amount"),
	]
	return columns, data, _group_summary(data, amount_field="amount", count_field="cheque_count")


def _cash_flow_forecast(filters):
	horizon = cint(filters.forecast_days) or 30
	if horizon not in (7, 30, 60, 90, 180):
		frappe.throw(_("Forecast period must be 7, 30, 60, 90, or 180 days."))
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	today = getdate(nowdate())
	end = getdate(add_days(today, horizon))
	periodicity = filters.periodicity or "Day"
	periods = {}
	for row in rows:
		expected_date = max(getdate(row.cheque_date), today)
		if expected_date > end:
			continue
		period = _period_label(expected_date, periodicity)
		item = periods.setdefault(
			period,
			frappe._dict(
				period=period,
				period_date=expected_date,
				company=row.company,
				expected_inflow=0.0,
				expected_outflow=0.0,
			),
		)
		field = "expected_inflow" if row.direction == "Inbound" else "expected_outflow"
		item[field] += flt(row.base_amount)
	for item in periods.values():
		item.net_expected_cash_flow = item.expected_inflow - item.expected_outflow
	data = sorted(periods.values(), key=lambda row: row.period_date)
	columns = [
		_col("Period", "period", width=140),
		_currency_column("Expected Inflow", "expected_inflow", 150),
		_currency_column("Expected Outflow", "expected_outflow", 150),
		_currency_column("Net Expected Cash Flow", "net_expected_cash_flow", 180),
	]
	inflow = sum(row.expected_inflow for row in data)
	outflow = sum(row.expected_outflow for row in data)
	summary = [
		_summary(_("Expected Inflow"), inflow, "Currency", "Green", _company_currency(filters)),
		_summary(_("Expected Outflow"), outflow, "Currency", "Orange", _company_currency(filters)),
		_summary(
			_("Net Expected Cash Flow"), inflow - outflow, "Currency", "Blue", _company_currency(filters)
		),
	]
	chart = {
		"data": {
			"labels": [row.period for row in data],
			"datasets": [
				{"name": _("Expected Inflow"), "values": [row.expected_inflow for row in data]},
				{"name": _("Expected Outflow"), "values": [row.expected_outflow for row in data]},
				{"name": _("Net Expected Cash Flow"), "values": [row.net_expected_cash_flow for row in data]},
			],
		},
		"type": "line",
	}
	return columns, data, None, chart, summary


def _period_label(value, periodicity):
	value = getdate(value)
	if periodicity == "Week":
		year, week, _weekday = value.isocalendar()
		return f"{year}-W{week:02d}"
	if periodicity == "Month":
		return value.strftime("%Y-%m")
	return value.isoformat()


def _cheques_by_bank(filters):
	rows = _get_cheques(filters, unlimited=True)
	groups = {}
	for row in rows:
		bank = row.bank_account or row.drawee_bank or _("Not Set")
		item = groups.setdefault(
			(bank, row.company),
			frappe._dict(
				bank=bank,
				company=row.company,
				inbound=0.0,
				outbound=0.0,
				deposited=0.0,
				pending_clearance=0.0,
				cleared=0.0,
				bounced=0.0,
			),
		)
		amount = flt(row.base_amount)
		item[row.direction.lower()] += amount
		if row.status == "Deposited":
			item.deposited += amount
			item.pending_clearance += amount
		elif row.status == "Cleared":
			item.cleared += amount
		elif row.bounce_journal_entry:
			item.bounced += amount
	for item in groups.values():
		item.net_position = item.inbound - item.outbound
	data = sorted(groups.values(), key=lambda row: abs(row.net_position), reverse=True)
	columns = [
		_col("Bank", "bank", width=200),
		_currency_column("Inbound", "inbound"),
		_currency_column("Outbound", "outbound"),
		_currency_column("Deposited", "deposited"),
		_currency_column("Pending Clearance", "pending_clearance", 150),
		_currency_column("Cleared", "cleared"),
		_currency_column("Bounced", "bounced"),
		_currency_column("Net Position", "net_position"),
	]
	return columns, data, _group_summary(data, amount_field="net_position", count_field=None)


def _bounced_analysis(filters):
	all_rows = _get_cheques(filters, unlimited=True)
	bounced = [row for row in all_rows if row.bounce_journal_entry]
	group_by = filters.group_by or "Customer"
	groups = {}
	all_counts = defaultdict(int)
	for row in all_rows:
		group = _bounce_group(row, group_by)
		if group:
			all_counts[group] += 1
	for row in bounced:
		group = _bounce_group(row, group_by)
		if not group:
			continue
		item = groups.setdefault(
			group,
			frappe._dict(
				group=group, company=row.company, cheque_count=0, bounced_amount=0.0, bounce_rate=0.0
			),
		)
		item.cheque_count += 1
		item.bounced_amount += flt(row.base_amount)
	for group, item in groups.items():
		item.bounce_rate = item.cheque_count / all_counts[group] * 100 if all_counts[group] else 0
		item.repeated_bouncer = 1 if item.cheque_count >= (cint(filters.repeated_bounce_count) or 2) else 0
	data = sorted(groups.values(), key=lambda row: (row.cheque_count, row.bounced_amount), reverse=True)
	columns = [
		_col("Group", "group", width=200),
		_col("Bounced Cheques", "cheque_count", "Int"),
		_currency_column("Bounced Amount", "bounced_amount", 150),
		_col("Bounce Rate", "bounce_rate", "Percent"),
		_col("Repeated Bouncer", "repeated_bouncer", "Check"),
	]
	rate = len(bounced) / len(all_rows) * 100 if all_rows else 0
	summary = [
		_summary(_("Bounced Cheques"), len(bounced), "Int", "Red"),
		_summary(
			_("Bounced Amount"),
			sum(flt(row.base_amount) for row in bounced),
			"Currency",
			"Red",
			_company_currency(filters),
		),
		_summary(_("Bounce Rate"), rate, "Percent", "Orange"),
	]
	return columns, data, summary


def _bounce_group(row, group_by):
	if group_by == "Month":
		return getdate(row.bounce_date).strftime("%Y-%m") if row.bounce_date else None
	if group_by == "Bank":
		return row.bank_account or row.drawee_bank or _("Not Set")
	if group_by == "Supplier" and row.party_type != "Supplier":
		return None
	if group_by == "Customer" and row.party_type != "Customer":
		return None
	return row.party


def _customer_exposure(filters):
	return _exposure_report(filters, "Customer")


def _supplier_exposure(filters):
	return _exposure_report(filters, "Supplier")


def _exposure_report(filters, party_type):
	_check_gl_permission()
	direction = "Inbound" if party_type == "Customer" else "Outbound"
	rows = _get_cheques(filters, direction=direction, unlimited=True)
	groups = {}
	for row in rows:
		item = groups.setdefault(
			row.party,
			frappe._dict(
				party=row.party,
				party_name=row.party_name,
				company=row.company,
				accounting_balance=0.0,
				received_or_issued=0.0,
				post_dated=0.0,
				deposited=0.0,
				bounced=0.0,
				outstanding_cheque_exposure=0.0,
				total_exposure=0.0,
			),
		)
		amount = flt(row.base_amount)
		if row.status in ("Received", "Issued"):
			item.received_or_issued += amount
		elif row.status == "Post-Dated Held":
			item.post_dated += amount
		elif row.status == "Deposited":
			item.deposited += amount
		if row.bounce_journal_entry:
			item.bounced += amount
		if row.status in (INBOUND_LIVE if direction == "Inbound" else OUTBOUND_LIVE):
			item.outstanding_cheque_exposure += amount
	balances = _party_gl_balances(filters, party_type)
	for party, balance in balances.items():
		if party not in groups:
			name = frappe.db.get_value(
				party_type,
				party,
				"customer_name" if party_type == "Customer" else "supplier_name",
			)
			groups[party] = frappe._dict(
				party=party,
				party_name=name or party,
				company=filters.company,
				accounting_balance=0.0,
				received_or_issued=0.0,
				post_dated=0.0,
				deposited=0.0,
				bounced=0.0,
				outstanding_cheque_exposure=0.0,
				total_exposure=0.0,
			)
		groups[party].accounting_balance = balance
	for item in groups.values():
		item.total_exposure = item.accounting_balance + item.outstanding_cheque_exposure
	data = sorted(groups.values(), key=lambda row: row.total_exposure, reverse=True)
	account_label = "Accounts Receivable" if party_type == "Customer" else "Accounts Payable"
	columns = [
		_col(party_type, "party", "Link", party_type, 160),
		_col("Party Name", "party_name", width=180),
		_currency_column(account_label, "accounting_balance", 150),
		_currency_column("Received" if party_type == "Customer" else "Issued", "received_or_issued"),
		_currency_column("Post-Dated", "post_dated"),
	]
	if party_type == "Customer":
		columns.append(_currency_column("Deposited", "deposited"))
	columns.extend(
		[
			_currency_column("Bounced", "bounced"),
			_currency_column("Outstanding Cheque Exposure", "outstanding_cheque_exposure", 190),
			_currency_column("Total Exposure", "total_exposure", 150),
		]
	)
	return columns, data, _group_summary(data, amount_field="total_exposure", count_field=None)


def _party_gl_balances(filters, party_type):
	gl_filters = {"is_cancelled": 0, "party_type": party_type}
	if filters.company:
		gl_filters["company"] = filters.company
	if filters.to_date:
		gl_filters["posting_date"] = ["<=", filters.to_date]
	party_filter = filters.customer if party_type == "Customer" else filters.supplier
	if party_filter:
		gl_filters["party"] = party_filter
	entries = frappe.get_list(
		"GL Entry",
		filters=gl_filters,
		fields=["party", "sum(debit) as debit", "sum(credit) as credit"],
		group_by="party",
		order_by=None,
		limit_page_length=0,
	)
	if party_type == "Customer":
		return {row.party: flt(row.debit) - flt(row.credit) for row in entries if row.party}
	return {row.party: flt(row.credit) - flt(row.debit) for row in entries if row.party}


def _bank_reconciliation(filters):
	rows = _get_cheques(filters, unlimited=True, order_by="bank_account asc, cheque_date asc")
	rows = [
		row
		for row in rows
		if row.status in ("Deposited", "Cleared", "Bounced", "Issued") or row.bounce_journal_entry
	]
	for row in rows:
		row.reconciliation_category = {
			"Deposited": _("Deposited but not Cleared"),
			"Cleared": _("Cleared"),
			"Issued": _("Issued but not Cleared"),
		}.get(row.status, _("Bounced"))
		row.payment_entry = row.clear_payment_entry or row.source_payment_entry
	columns = [
		_col("Category", "reconciliation_category", width=180),
		_col("Bank", "bank_account", "Link", "Account", 180),
		_col("Cheque", "name", "Link", CHEQUE, 130),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Party", "party", "Dynamic Link", "party_type", 150),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Payment Entry", "payment_entry", "Link", "Payment Entry", 150),
		_col("Deposit Journal Entry", "deposit_journal_entry", "Link", "Journal Entry", 160),
		_col("Status", "status"),
	]
	return columns, rows, _amount_summary(rows, _("Cheque Transactions"), _("Total Amount"))


def _accounting_reconciliation(filters):
	_check_gl_permission()
	company = filters.company
	if not company:
		frappe.throw(_("Company is required for accounting reconciliation."))
	types = frappe.get_list(
		CHEQUE_TYPE,
		filters={"company": company},
		fields=["name", "direction", "clearing_account", "transit_account", "post_dated_account"],
		limit_page_length=0,
	)
	accounts = {
		account
		for row in types
		for account in (row.clearing_account, row.transit_account, row.post_dated_account)
		if account
	}
	account_details = {
		row.name: row
		for row in frappe.get_all(
			"Account", filters={"name": ["in", list(accounts)]}, fields=["name", "root_type"]
		)
	}
	gl_filters = {"company": company, "is_cancelled": 0, "account": ["in", list(accounts)]}
	if filters.to_date:
		gl_filters["posting_date"] = ["<=", filters.to_date]
	gl_rows = (
		frappe.get_list(
			"GL Entry",
			filters=gl_filters,
			fields=["account", "sum(debit) as debit", "sum(credit) as credit"],
			group_by="account",
			order_by=None,
			limit_page_length=0,
		)
		if accounts
		else []
	)
	gl_balances = {}
	for row in gl_rows:
		net = flt(row.debit) - flt(row.credit)
		if (account_details.get(row.account) or {}).get("root_type") in ("Liability", "Equity", "Income"):
			net *= -1
		gl_balances[row.account] = net

	type_map = {row.name: row for row in types}
	cheques = _get_cheques(frappe._dict({"company": company}), unlimited=True)
	expected = defaultdict(float)
	cheque_names = defaultdict(list)
	for cheque in cheques:
		type_row = type_map.get(cheque.cheque_type)
		if not type_row:
			continue
		account = None
		if cheque.status == "Post-Dated Held":
			account = type_row.post_dated_account
		elif cheque.status in ("Received", "Issued"):
			account = type_row.clearing_account
		elif cheque.status == "Deposited" and cheque.direction == "Inbound":
			account = type_row.transit_account
		if account:
			expected[account] += flt(cheque.base_amount)
			cheque_names[account].append(cheque.name)
	tolerance = flt(filters.tolerance)
	data = []
	for account in sorted(accounts):
		gl_balance = gl_balances.get(account, 0.0)
		cm_balance = expected.get(account, 0.0)
		difference = gl_balance - cm_balance
		status = (
			"Reconciled"
			if abs(difference) <= tolerance
			else ("Warning" if abs(difference) <= max(tolerance * 10, 1) else "Exception")
		)
		data.append(
			frappe._dict(
				account=account,
				company=company,
				gl_balance=gl_balance,
				cheque_management_balance=cm_balance,
				difference=difference,
				cheque_count=len(cheque_names[account]),
				status=status,
				cheques=", ".join(cheque_names[account][:20]),
			)
		)
	columns = [
		_col("Account", "account", "Link", "Account", 220),
		_currency_column("GL Balance", "gl_balance"),
		_currency_column("Cheque Management Balance", "cheque_management_balance", 200),
		_currency_column("Difference", "difference"),
		_col("Number of Cheques", "cheque_count", "Int"),
		_col("Status", "status"),
		_col("Cheque Transactions", "cheques", width=260),
	]
	total_difference = sum(row.difference for row in data)
	exceptions = sum(1 for row in data if row.status != "Reconciled")
	summary = [
		_summary(
			_("GL Reconciliation Difference"),
			total_difference,
			"Currency",
			"Red" if exceptions else "Green",
			_company_currency(filters),
		),
		_summary(_("Accounting Exceptions"), exceptions, "Int", "Red" if exceptions else "Green"),
	]
	message = None
	if filters.to_date and getdate(filters.to_date) != getdate(nowdate()):
		message = _(
			"GL is shown as of the selected date; Cheque Management is a current-state subledger. See Review Notes for the historical snapshot limitation."
		)
	return columns, data, message, None, summary


def _audit_trail(filters):
	cheques = _get_cheques(filters, unlimited=True, order_by="creation asc")
	data = []
	for cheque in cheques:
		data.append(
			_audit_row(cheque, cheque.creation, cheque.owner, None, _initial_status(cheque), _("Created"))
		)
		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": CHEQUE, "docname": cheque.name},
			fields=["creation", "owner", "data"],
			order_by="creation asc",
		)
		for version in versions:
			payload = frappe.parse_json(version.data) or {}
			for changed in payload.get("changed") or []:
				if len(changed) >= 3 and changed[0] == "status":
					data.append(
						_audit_row(
							cheque,
							version.creation,
							version.owner,
							changed[1],
							changed[2],
							_action_for_status(changed[2]),
						)
					)
	data.sort(key=lambda row: row.event_datetime, reverse=True)
	_hydrate_audit_accounts(data)
	columns = [
		_col("Cheque", "cheque", "Link", CHEQUE, 130),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Date", "date", "Date"),
		_col("Time", "time", "Time"),
		_col("User", "user", "Link", "User", 160),
		_col("Previous Status", "previous_status", width=140),
		_col("New Status", "new_status", width=140),
		_col("Action", "action", width=140),
		_col("Accounting Document", "accounting_document", "Dynamic Link", "accounting_doctype", 170),
		_currency_column("Amount", "amount"),
		_col("Debit", "debit", width=220),
		_col("Credit", "credit", width=220),
	]
	return columns, data


def _initial_status(cheque):
	if cheque.source_posting_date and getdate(cheque.cheque_date) > getdate(cheque.source_posting_date):
		return "Post-Dated Held"
	return "Received" if cheque.direction == "Inbound" else "Issued"


def _audit_row(cheque, event_datetime, user, previous_status, new_status, action):
	doctype, document = _accounting_document_for_status(cheque, new_status)
	if isinstance(event_datetime, str):
		event_datetime = datetime.fromisoformat(event_datetime)
	return frappe._dict(
		cheque=cheque.name,
		cheque_number=cheque.cheque_number,
		company=cheque.company,
		event_datetime=event_datetime,
		date=event_datetime.date(),
		time=event_datetime.time(),
		user=user,
		previous_status=previous_status,
		new_status=new_status,
		action=action,
		accounting_doctype=doctype,
		accounting_document=document,
		amount=cheque.base_amount,
		debit=None,
		credit=None,
	)


def _accounting_document_for_status(cheque, status):
	if status in ("Post-Dated Held", "Received", "Issued"):
		return "Payment Entry", cheque.source_payment_entry
	if status == "Deposited":
		return "Journal Entry", cheque.deposit_journal_entry
	if status == "Cleared":
		return "Payment Entry", cheque.clear_payment_entry
	if status == "Bounced":
		return "Journal Entry", cheque.bounce_journal_entry
	return None, None


def _hydrate_audit_accounts(rows):
	if not rows or not frappe.has_permission("GL Entry", "read"):
		return
	vouchers = list({row.accounting_document for row in rows if row.accounting_document})
	if not vouchers:
		return
	entries = frappe.get_list(
		"GL Entry",
		filters={"voucher_no": ["in", vouchers], "is_cancelled": 0},
		fields=["voucher_type", "voucher_no", "account", "debit", "credit"],
		order_by="voucher_no asc, account asc",
		limit_page_length=0,
	)
	debits = defaultdict(list)
	credits = defaultdict(list)
	for entry in entries:
		key = (entry.voucher_type, entry.voucher_no)
		if flt(entry.debit):
			debits[key].append(f"{entry.account}: {flt(entry.debit):g}")
		if flt(entry.credit):
			credits[key].append(f"{entry.account}: {flt(entry.credit):g}")
	for row in rows:
		key = (row.accounting_doctype, row.accounting_document)
		row.debit = ", ".join(debits[key])
		row.credit = ", ".join(credits[key])


def _action_for_status(status):
	return {
		"Post-Dated Held": _("Captured"),
		"Received": _("Matured / Received"),
		"Issued": _("Matured / Issued"),
		"Deposited": _("Deposited"),
		"Cleared": _("Cleared"),
		"Bounced": _("Bounced"),
		"Returned to Customer": _("Returned to Customer"),
		"Replaced": _("Replaced"),
		"Cancelled": _("Cancelled"),
	}.get(status, status)


def _cancelled_cheques(filters):
	rows = _get_cheques(filters, statuses=("Cancelled",), order_by="modified desc")
	for row in rows:
		row.original_status = row.get("cancelled_from_status") or _previous_status_from_version(row.name)
		row.cancellation_date = row.get("cancellation_date") or getdate(row.modified)
		row.cancelled_by = row.get("cancelled_by") or row.modified_by
		row.cancellation_reason = row.get("cancellation_reason")
		row.related_accounting_documents = ", ".join(
			name
			for name in (
				row.source_payment_entry,
				row.maturity_journal_entry,
				row.deposit_journal_entry,
				row.clear_payment_entry,
				row.bounce_journal_entry,
			)
			if name
		)
	columns = [
		_col("Cheque", "name", "Link", CHEQUE),
		_col("Cheque Number", "cheque_number", width=140),
		_col("Party", "party", "Dynamic Link", "party_type", 150),
		_col("Amount", "amount", "Currency", "currency", 130),
		_col("Original Status", "original_status", width=140),
		_col("Cancellation Date", "cancellation_date", "Date"),
		_col("Cancelled By", "cancelled_by", "Link", "User", 160),
		_col("Cancellation Reason", "cancellation_reason", width=220),
		_col("Related Accounting Documents", "related_accounting_documents", width=260),
	]
	return columns, rows, _amount_summary(rows, _("Cancelled Cheques"), _("Cancelled Amount"))


def _previous_status_from_version(cheque):
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": CHEQUE, "docname": cheque},
		fields=["data"],
		order_by="creation desc",
		limit_page_length=20,
	)
	for version in versions:
		payload = frappe.parse_json(version.data) or {}
		for changed in payload.get("changed") or []:
			if len(changed) >= 3 and changed[0] == "status" and changed[2] == "Cancelled":
				return changed[1]
	return None


def _group_value(row, group_by):
	return {
		"Customer": row.party if row.party_type == "Customer" else None,
		"Supplier": row.party if row.party_type == "Supplier" else None,
		"Party": row.party,
		"Bank": row.bank_account or row.drawee_bank or _("Not Set"),
		"Currency": row.currency,
		"Cheque Type": row.cheque_type,
	}.get(group_by, row.party)


def _aging_thresholds(filters, defaults):
	values = (
		cint(filters.aging_threshold_1) or defaults[0],
		cint(filters.aging_threshold_2) or defaults[1],
		cint(filters.aging_threshold_3) or defaults[2],
	)
	if values != tuple(sorted(values)):
		frappe.throw(_("Aging thresholds must be in ascending order."))
	return values


def _bucket(value, thresholds, labels):
	for index, threshold in enumerate(thresholds):
		if value <= threshold:
			return _(labels[index])
	return _(labels[-1])


def _company_currency(filters):
	return (
		frappe.get_cached_value("Company", filters.company, "default_currency") if filters.company else None
	)


def _summary(label, value, datatype, indicator, currency=None):
	item = {"label": label, "value": value, "datatype": datatype, "indicator": indicator}
	if currency:
		item["currency"] = currency
	return item


def _amount_summary(rows, count_label, amount_label):
	company = rows[0].company if rows and all(row.company == rows[0].company for row in rows) else None
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	return [
		_summary(count_label, len(rows), "Int", "Blue"),
		_summary(amount_label, sum(flt(row.base_amount) for row in rows), "Currency", "Blue", currency),
	]


def _group_summary(rows, amount_field="total_exposure", count_field=None):
	count = sum(cint(row.get(count_field)) for row in rows) if count_field else len(rows)
	return [
		_summary(_("Groups"), count, "Int", "Blue"),
		_summary(_("Total Amount"), sum(flt(row.get(amount_field)) for row in rows), "Currency", "Blue"),
	]
