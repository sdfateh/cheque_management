# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Data sources for the standard CFO cheque dashboard, cards, charts, and alerts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

import frappe
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from cheque_management.cheque_management.doctype.mfg_cheque_settings.mfg_cheque_settings import (
	get_company_settings,
)
from cheque_management.i18n import _
from cheque_management.reporting import (
	INBOUND_LIVE,
	LIVE_STATUSES,
	OUTBOUND_LIVE,
	_accounting_reconciliation,
	_check_cheque_permission,
	_filters,
	_get_cheques,
	_period_label,
)

MANAGEMENT_ROLES = ("Accounts Manager", "Cheque Manager", "System Manager")

CARD_DEFINITIONS = {
	"inbound_received": (
		_("Total Received Cheques"),
		"Currency",
		"Cheque Register",
		{"direction": "Inbound", "status": "Received"},
	),
	"inbound_pdc": (
		_("Total Inbound PDC"),
		"Currency",
		"Cheque Register",
		{"direction": "Inbound", "status": "Post-Dated Held"},
	),
	"inbound_deposited": (_("Total Deposited"), "Currency", "Deposited Pending Clearance", {}),
	"inbound_cleared": (
		_("Total Inbound Cleared"),
		"Currency",
		"Cheque Register",
		{"direction": "Inbound", "status": "Cleared"},
	),
	"inbound_bounced": (_("Total Inbound Bounced"), "Currency", "Bounced Cheques", {"direction": "Inbound"}),
	"outbound_issued": (
		_("Total Issued"),
		"Currency",
		"Cheque Register",
		{"direction": "Outbound", "status": "Issued"},
	),
	"outbound_pdc": (
		_("Total Outbound PDC"),
		"Currency",
		"Cheque Register",
		{"direction": "Outbound", "status": "Post-Dated Held"},
	),
	"outbound_cleared": (
		_("Total Outbound Cleared"),
		"Currency",
		"Cheque Register",
		{"direction": "Outbound", "status": "Cleared"},
	),
	"outbound_bounced": (
		_("Total Outbound Bounced"),
		"Currency",
		"Bounced Cheques",
		{"direction": "Outbound"},
	),
	"overdue": (_("Overdue Cheques"), "Currency", "Cheques Due Maturity", {}),
	"due_7": (_("Cheques Due Next 7 Days"), "Currency", "Cheques Due Maturity", {}),
	"due_30": (_("Cheques Due Next 30 Days"), "Currency", "Cheques Due Maturity", {}),
	"bounced": (_("Bounced Cheques"), "Currency", "Bounced Cheques", {}),
	"large_value": (_("Large-Value Cheques"), "Currency", "Cheque Register", {}),
	"expected_inflow": (
		_("Expected Inflow"),
		"Currency",
		"Cheque Cash Flow Forecast",
		{"direction": "Inbound"},
	),
	"expected_outflow": (
		_("Expected Outflow"),
		"Currency",
		"Cheque Cash Flow Forecast",
		{"direction": "Outbound"},
	),
	"net_cash_flow": (_("Net Expected Cash Flow"), "Currency", "Cheque Cash Flow Forecast", {}),
	"total_exposure": (_("Total Cheque Exposure"), "Currency", "Cheque Position", {}),
	"reconciliation_difference": (
		_("GL Reconciliation Difference"),
		"Currency",
		"Cheque Accounting Reconciliation",
		{},
	),
	"accounting_exceptions": (
		_("Number of Accounting Exceptions"),
		"Int",
		"Cheque Accounting Reconciliation",
		{},
	),
}


@frappe.whitelist()
def get_number_card(filters=None):
	_check_management_permission()
	filters = _filters(filters)
	_check_cheque_permission()
	metric = filters.metric
	if metric not in CARD_DEFINITIONS:
		frappe.throw(_("Unknown CFO cheque metric: {0}").format(metric))
	value = _cached_metric(metric, filters)
	label, fieldtype, report, route_options = CARD_DEFINITIONS[metric]
	options = dict(route_options)
	for key in ("company", "currency", "bank_account", "customer", "supplier", "direction"):
		if filters.get(key):
			options[key] = filters.get(key)
	if metric in ("expected_inflow", "expected_outflow", "net_cash_flow"):
		options["forecast_days"] = cint(filters.forecast_days) or _settings(filters).default_forecast_days
	return {
		"value": value,
		"fieldtype": fieldtype,
		"label": label,
		"route": ["query-report", report],
		"route_options": options,
	}


def _cached_metric(metric, filters):
	minutes = cint(_settings(filters).dashboard_cache_minutes)
	key_payload = json.dumps(dict(filters), sort_keys=True, default=str)
	key = f"cfo_cheque_card:{frappe.session.user}:{metric}:{hashlib.sha256(key_payload.encode()).hexdigest()}"
	if minutes:
		cached = frappe.cache.get_value(key)
		if cached is not None:
			return cached
	value = _metric_value(metric, filters)
	if minutes:
		frappe.cache.set_value(key, value, expires_in_sec=minutes * 60)
	return value


def _metric_value(metric, filters):
	rows = _get_cheques(filters, unlimited=True)
	today = getdate(nowdate())
	settings = _settings(filters)

	def total(predicate):
		return sum(flt(row.base_amount) for row in rows if predicate(row))

	status_metrics = {
		"inbound_received": ("Inbound", "Received"),
		"inbound_pdc": ("Inbound", "Post-Dated Held"),
		"inbound_deposited": ("Inbound", "Deposited"),
		"inbound_cleared": ("Inbound", "Cleared"),
		"inbound_bounced": ("Inbound", "Bounced"),
		"outbound_issued": ("Outbound", "Issued"),
		"outbound_pdc": ("Outbound", "Post-Dated Held"),
		"outbound_cleared": ("Outbound", "Cleared"),
		"outbound_bounced": ("Outbound", "Bounced"),
	}
	if metric in status_metrics:
		direction, status = status_metrics[metric]
		if status == "Bounced":
			return total(lambda row: row.direction == direction and bool(row.bounce_journal_entry))
		return total(lambda row: row.direction == direction and row.status == status)
	if metric == "overdue":
		return total(lambda row: row.status in LIVE_STATUSES and getdate(row.cheque_date) < today)
	if metric == "due_7":
		return total(lambda row: row.status in LIVE_STATUSES and 0 <= date_diff(row.cheque_date, today) <= 7)
	if metric == "due_30":
		return total(lambda row: row.status in LIVE_STATUSES and 0 <= date_diff(row.cheque_date, today) <= 30)
	if metric == "bounced":
		return total(lambda row: bool(row.bounce_journal_entry))
	if metric == "large_value":
		threshold = flt(settings.large_value_threshold)
		return total(
			lambda row: threshold and row.status in LIVE_STATUSES and flt(row.base_amount) >= threshold
		)
	if metric in ("expected_inflow", "expected_outflow", "net_cash_flow"):
		horizon = cint(filters.forecast_days) or cint(settings.default_forecast_days) or 30
		end = getdate(add_days(today, horizon))
		inflow = total(lambda row: row.status in INBOUND_LIVE and max(getdate(row.cheque_date), today) <= end)
		outflow = total(
			lambda row: row.status in OUTBOUND_LIVE and max(getdate(row.cheque_date), today) <= end
		)
		return {"expected_inflow": inflow, "expected_outflow": outflow, "net_cash_flow": inflow - outflow}[
			metric
		]
	if metric == "total_exposure":
		return total(lambda row: row.status in LIVE_STATUSES)
	if metric in ("reconciliation_difference", "accounting_exceptions"):
		if not filters.company:
			return 0
		reconciliation_filters = frappe._dict(
			company=filters.company,
			to_date=nowdate(),
			tolerance=settings.reconciliation_tolerance,
		)
		_columns, data, _message, _chart, _summary = _accounting_reconciliation(reconciliation_filters)
		if metric == "reconciliation_difference":
			return sum(flt(row.difference) for row in data)
		return sum(1 for row in data if row.status != "Reconciled")
	return 0


@frappe.whitelist()
def get_chart(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	_check_management_permission()
	_check_cheque_permission()
	filters = _filters(filters)
	if chart_name:
		chart_doc = frappe.get_doc("Dashboard Chart", chart_name)
		chart_doc.check_permission("read")
		stored = _filters(chart_doc.filters_json)
		for key, value in stored.items():
			filters.setdefault(key, value)
	metric = filters.metric
	builders = {
		"inbound_vs_outbound": _chart_inbound_outbound,
		"status_distribution": _chart_status_distribution,
		"cash_flow_forecast": _chart_cash_flow,
		"maturity": _chart_maturity,
		"bounced_trend": _chart_bounced_trend,
		"top_customers": lambda f: _chart_top_parties(f, "Customer"),
		"top_suppliers": lambda f: _chart_top_parties(f, "Supplier"),
		"banks": _chart_banks,
		"aging": _chart_aging,
		"exceptions": _chart_exceptions,
	}
	if metric not in builders:
		frappe.throw(_("Unknown CFO cheque chart: {0}").format(metric))
	return builders[metric](filters)


def _chart_inbound_outbound(filters):
	rows = _get_cheques(filters, unlimited=True)
	groups = defaultdict(lambda: {"Inbound": 0.0, "Outbound": 0.0})
	for row in rows:
		period = getdate(row.source_posting_date or row.cheque_date).strftime("%Y-%m")
		groups[period][row.direction] += flt(row.base_amount)
	labels = sorted(groups)
	return _chart(
		labels,
		[
			(_("Inbound"), [groups[p]["Inbound"] for p in labels]),
			(_("Outbound"), [groups[p]["Outbound"] for p in labels]),
		],
		"bar",
	)


def _chart_status_distribution(filters):
	rows = _get_cheques(filters, unlimited=True)
	groups = defaultdict(float)
	for row in rows:
		groups[_(row.status)] += flt(row.base_amount)
	labels = sorted(groups)
	return _chart(labels, [(_("Amount"), [groups[label] for label in labels])], "donut")


def _chart_cash_flow(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	today = getdate(nowdate())
	horizon = cint(filters.forecast_days) or cint(_settings(filters).default_forecast_days) or 30
	end = getdate(add_days(today, horizon))
	periodicity = filters.periodicity or "Day"
	groups = defaultdict(lambda: {"inflow": 0.0, "outflow": 0.0})
	for row in rows:
		expected = max(getdate(row.cheque_date), today)
		if expected > end:
			continue
		period = _period_label(expected, periodicity)
		groups[period]["inflow" if row.direction == "Inbound" else "outflow"] += flt(row.base_amount)
	labels = sorted(groups)
	return _chart(
		labels,
		[
			(_("Expected Inflow"), [groups[p]["inflow"] for p in labels]),
			(_("Expected Outflow"), [groups[p]["outflow"] for p in labels]),
			(_("Net Cash Flow"), [groups[p]["inflow"] - groups[p]["outflow"] for p in labels]),
		],
		"line",
	)


def _chart_maturity(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	today = getdate(nowdate())
	labels = [
		_("Overdue"),
		_("Today"),
		_("1–7 Days"),
		_("8–30 Days"),
		_("31–60 Days"),
		_("61–90 Days"),
		_("Over 90 Days"),
	]
	values = [0.0] * len(labels)
	for row in rows:
		days = date_diff(row.cheque_date, today)
		index = (
			0
			if days < 0
			else 1
			if days == 0
			else 2
			if days <= 7
			else 3
			if days <= 30
			else 4
			if days <= 60
			else 5
			if days <= 90
			else 6
		)
		values[index] += flt(row.base_amount)
	return _chart(labels, [(_("Amount Due"), values)], "bar")


def _chart_bounced_trend(filters):
	rows = [
		row for row in _get_cheques(filters, unlimited=True) if row.bounce_journal_entry and row.bounce_date
	]
	groups = defaultdict(lambda: {"count": 0, "amount": 0.0})
	for row in rows:
		period = getdate(row.bounce_date).strftime("%Y-%m")
		groups[period]["count"] += 1
		groups[period]["amount"] += flt(row.base_amount)
	labels = sorted(groups)
	return _chart(
		labels,
		[
			(_("Count"), [groups[p]["count"] for p in labels]),
			(_("Amount"), [groups[p]["amount"] for p in labels]),
		],
		"line",
	)


def _chart_top_parties(filters, party_type):
	direction = "Inbound" if party_type == "Customer" else "Outbound"
	live = INBOUND_LIVE if direction == "Inbound" else OUTBOUND_LIVE
	rows = _get_cheques(filters, statuses=live, direction=direction, unlimited=True)
	groups = defaultdict(float)
	for row in rows:
		groups[row.party_name or row.party] += flt(row.base_amount)
	items = sorted(groups.items(), key=lambda item: item[1], reverse=True)[:10]
	return _chart([item[0] for item in items], [(_("Exposure"), [item[1] for item in items])], "bar")


def _chart_banks(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	groups = defaultdict(float)
	for row in rows:
		groups[row.bank_account or row.drawee_bank or _("Not Set")] += flt(row.base_amount)
	items = sorted(groups.items(), key=lambda item: item[1], reverse=True)[:10]
	return _chart([item[0] for item in items], [(_("Exposure"), [item[1] for item in items])], "bar")


def _chart_aging(filters):
	rows = _get_cheques(filters, statuses=LIVE_STATUSES, unlimited=True)
	labels = [_("0–7 Days"), _("8–30 Days"), _("31–60 Days"), _("61–90 Days"), _("> 90 Days")]
	values = [0.0] * len(labels)
	for row in rows:
		age = max(date_diff(nowdate(), row.source_posting_date or row.cheque_date), 0)
		index = 0 if age <= 7 else 1 if age <= 30 else 2 if age <= 60 else 3 if age <= 90 else 4
		values[index] += flt(row.base_amount)
	return _chart(labels, [(_("Exposure"), values)], "bar")


def _chart_exceptions(filters):
	if not filters.company:
		return _chart([], [(_("Difference"), [])], "bar")
	filters.tolerance = _settings(filters).reconciliation_tolerance
	_columns, data, _message, _chart_data, _summary = _accounting_reconciliation(filters)
	data = [row for row in data if row.status != "Reconciled"]
	return _chart([row.account for row in data], [(_("Difference"), [row.difference for row in data])], "bar")


def _chart(labels, datasets, chart_type):
	return {
		"labels": labels,
		"datasets": [{"name": name, "values": values} for name, values in datasets],
		"type": chart_type,
	}


@frappe.whitelist()
def get_alerts(filters=None):
	_check_management_permission()
	filters = _filters(filters)
	_check_cheque_permission()
	rows = _get_cheques(filters, unlimited=True)
	settings = _settings(filters)
	type_defaults = {
		row.name: row.default_bank_account
		for row in frappe.get_list(
			"MFG Cheque Type",
			filters={"company": filters.company} if filters.company else {},
			fields=["name", "default_bank_account"],
			limit_page_length=0,
		)
	}
	today = getdate(nowdate())
	alerts = []

	def add_alert(key, label, matching, severity, report, route_options=None):
		matching = list(matching)
		if not matching:
			return
		alerts.append(
			{
				"key": key,
				"label": label,
				"count": len(matching),
				"amount": sum(flt(row.base_amount) for row in matching),
				"severity": severity,
				"route": ["query-report", report],
				"route_options": {"company": filters.company, **(route_options or {})},
			}
		)

	add_alert(
		"overdue",
		_("Overdue cheque"),
		(row for row in rows if row.status in LIVE_STATUSES and getdate(row.cheque_date) < today),
		"danger",
		"Cheques Due Maturity",
	)
	add_alert(
		"due_7",
		_("Cheque due within 7 days"),
		(row for row in rows if row.status in LIVE_STATUSES and 0 <= date_diff(row.cheque_date, today) <= 7),
		"warning",
		"Cheques Due Maturity",
	)
	threshold = flt(settings.large_value_threshold)
	if threshold:
		add_alert(
			"large_value",
			_("Large-value cheque"),
			(row for row in rows if row.status in LIVE_STATUSES and flt(row.base_amount) >= threshold),
			"warning",
			"Cheque Register",
		)
	add_alert(
		"bounced",
		_("Bounced cheque"),
		(row for row in rows if row.bounce_journal_entry),
		"danger",
		"Bounced Cheques",
	)
	clearance_days = cint(settings.deposited_clearance_days) or 10
	add_alert(
		"slow_clearance",
		_("Deposited cheque pending clearance for too long"),
		(
			row
			for row in rows
			if row.status == "Deposited"
			and row.deposit_date
			and date_diff(today, row.deposit_date) > clearance_days
		),
		"warning",
		"Deposited Pending Clearance",
	)
	add_alert(
		"missing_accounting",
		_("Missing accounting document"),
		(row for row in rows if _missing_accounting_document(row)),
		"danger",
		"Cheque Register",
	)
	add_alert(
		"missing_bank",
		_("Missing bank account"),
		(
			row
			for row in rows
			if row.status in LIVE_STATUSES
			and not (row.bank_account or type_defaults.get(row.cheque_type) or settings.default_bank_account)
		),
		"warning",
		"Cheque Register",
	)
	add_alert(
		"missing_type",
		_("Missing cheque type"),
		(row for row in rows if not row.cheque_type),
		"danger",
		"Cheque Register",
	)

	bounce_counts = defaultdict(int)
	for row in rows:
		if row.bounce_journal_entry:
			bounce_counts[(row.party_type, row.party)] += 1
	repeated = sum(
		1 for count in bounce_counts.values() if count >= (cint(settings.repeated_bounce_count) or 2)
	)
	if repeated:
		alerts.append(
			{
				"key": "repeat_bounce",
				"label": _("Customer or supplier with repeated bounced cheques"),
				"count": repeated,
				"amount": 0,
				"severity": "danger",
				"route": ["query-report", "Bounced Cheque Analysis"],
				"route_options": {"company": filters.company},
			}
		)

	if filters.company and frappe.has_permission("GL Entry", "read"):
		recon_filters = frappe._dict(
			company=filters.company, to_date=nowdate(), tolerance=settings.reconciliation_tolerance
		)
		_columns, reconciliation, _message, _chart_data, _summary = _accounting_reconciliation(recon_filters)
		exceptions = [row for row in reconciliation if row.status != "Reconciled"]
		if exceptions:
			alerts.append(
				{
					"key": "reconciliation",
					"label": _("Accounting reconciliation difference"),
					"count": len(exceptions),
					"amount": sum(abs(flt(row.difference)) for row in exceptions),
					"severity": "danger",
					"route": ["query-report", "Cheque Accounting Reconciliation"],
					"route_options": {"company": filters.company},
				}
			)
	return alerts


def _missing_accounting_document(row):
	if not row.source_payment_entry:
		return True
	return (
		(row.status == "Deposited" and not row.deposit_journal_entry)
		or (row.status == "Cleared" and not row.clear_payment_entry)
		or (row.status == "Bounced" and not row.bounce_journal_entry)
	)


def _check_management_permission():
	frappe.only_for(MANAGEMENT_ROLES)


def _settings(filters):
	if filters.company:
		return get_company_settings(filters.company)
	return frappe._dict(
		large_value_threshold=0,
		deposited_clearance_days=10,
		repeated_bounce_count=2,
		reconciliation_tolerance=0,
		default_forecast_days=30,
		dashboard_cache_minutes=0,
	)
