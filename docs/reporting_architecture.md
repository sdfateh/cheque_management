# Cheque Reporting and CFO Dashboard Architecture

## Sources and ownership

The operational source is `MFG Cheque`; the accounting source is `GL Entry`.
Linked Payment Entries and Journal Entries provide lifecycle posting dates and
drill-down. Reports never create or mutate accounting entries.

```text
Sales/Purchase Invoice
        ↓ allocation
Capture Payment Entry
        ↓ derived record
MFG Cheque
        ↓ lifecycle controller
Maturity/Deposit Journal Entry or Clear Payment Entry
        ↓ standard ERPNext posting
General Ledger
```

Inbound live exposure is Post-Dated Held + Received + Deposited. Outbound live
exposure is Post-Dated Held + Issued. Cleared items are historical and terminal;
bounced/cancelled/returned/replaced items are excluded from live exposure. A
bounced amount is shown separately as risk because the bounce voucher has already
restored the party balance.

## Reports

All 18 reports are standard Script Reports under
`cheque_management/cheque_management/report`. Their thin controllers delegate to
`cheque_management.reporting`, which centralizes:

- document permission checks and permission-aware `frappe.get_list` access;
- company, date, party, bank, currency, status, and Accounting Dimension filters;
- company-currency aggregation and status definitions;
- batched party, allocation, and lifecycle-date hydration;
- report summaries, charts, and Link/Dynamic Link drill-down columns.

Detail reports default to 500 rows and cap at 5,000. Management reports aggregate
on the server. Composite indexes cover company/status/date, party/status,
bank/status, and cheque type/status paths.

## Reconciliation

The control report reads configured Clearing, Under Collection, and Post-Dated
accounts dynamically from every `MFG Cheque Type`. Expected operational balance
is mapped by current state:

| State | Inbound ledger | Outbound ledger |
|---|---|---|
| Post-Dated Held | Post-Dated Account | Post-Dated Account |
| Received / Issued | Clearing Account | Clearing Account |
| Deposited | Under Collection Account | Not applicable |
| Terminal | None | None |

GL balances are normalized by account root type and compared in company currency.
Every non-zero difference beyond the configured tolerance is a Warning or
Exception. The account links to the Account record and the causing cheque names
are included for transaction investigation.

## CFO dashboard

`CFO Cheque Management Dashboard` is a native standard Dashboard containing 20
custom Number Cards and 10 custom Dashboard Charts. `CFO Cheque Management` is a
native Workspace with executive cards/charts, a dashboard shortcut, and links to
all reports. Each card returns a Query Report route with route options.

The chart source accepts Company, date range, Currency, Bank, Customer, Supplier,
Direction, and forecast-period filters. Forecast horizons are 7/30/60/90/180
days. Card results are cached per user and filter set for the company-configured
number of minutes, preventing cross-user permission leakage.

`cheque_management.cfo_dashboard.get_alerts` returns permission-scoped,
drill-down alerts for overdue/due cheques, large value, bounce/repeated bounce,
slow clearance, reconciliation differences, and missing accounting, bank, or
cheque-type references. Thresholds live in the per-company row of MFG Cheque
Settings.

## Security and refresh

Operational reports are registered for Accounts User, Accounts Manager, Cheque
Manager, and System Manager. Management reports/workspace are registered for
Accounts Manager, Cheque Manager, and System Manager. Registration is not the
security boundary: every report/card/chart/alert endpoint checks `MFG Cheque`
read permission, and GL-backed endpoints additionally check `GL Entry` read
permission.

Dashboard widgets use native Frappe refresh behavior. Cached cards expire at the
configured interval; chart sources refresh on widget refresh and respect the
active widget filters.
