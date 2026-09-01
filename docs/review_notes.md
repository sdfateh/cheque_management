# Review Notes

These notes reconcile the requested reporting package with the accounting and
state model already implemented by this app. Reports use the General Ledger as
the accounting source of truth and `MFG Cheque` as the operational source.

## 1. Inbound deposit does not recognize bank cash

- **Original Requirement:** Deposit an inbound cheque by debiting Bank and
  crediting Cheques Receivable/Post-Dated Cheques.
- **Issue:** A deposited cheque is not cleared cash. Recognizing Bank at deposit
  overstates liquidity and makes ERPNext Bank Clearance include value the bank
  has not accepted.
- **Recommended Solution:** Preserve the implemented two-step model: Deposit
  moves Clearing to Under Collection with a Journal Entry; Clear moves Under
  Collection to Bank with an Internal Transfer Payment Entry.
- **Accounting Impact:** Bank changes only on Clear. Deposited cheques remain an
  asset in the configured Under Collection account.
- **Technical Impact:** Deposit dates come from `deposit_journal_entry`; bank
  clearance dates come from `clear_payment_entry`.
- **Decision Required:** The reports adopt the existing production model. A
  change to direct-to-bank deposit would require a separately approved lifecycle
  and migration project.

## 2. Prompt statuses differ from the production state machine

- **Original Requirement:** Draft, Received, Post-Dated, Deposited, Cleared,
  Bounced, Waiting Customer Response, Issued, and Cancelled.
- **Issue:** `MFG Cheque` is derived from a submitted Payment Entry and therefore
  has no Draft. Its canonical statuses are Post-Dated Held, Received, Issued,
  Deposited, Cleared, Bounced, Returned to Customer, Replaced, and Cancelled.
- **Recommended Solution:** Use the server transition map and stored statuses
  verbatim. Present friendly report labels without inventing states.
- **Accounting Impact:** None; this prevents reports from assigning accounting
  meaning to states that cannot exist.
- **Technical Impact:** “Post-Dated” maps to `Post-Dated Held`; “Waiting Customer
  Response” is represented operationally by `Bounced` until return/replacement.
- **Decision Required:** The reports use the authoritative production statuses.

## 3. Due date is the cheque date

- **Original Requirement:** Filter and report both Cheque Date and Due Date.
- **Issue:** The production schema stores one date written on the cheque,
  `cheque_date`; there is no independent due date.
- **Recommended Solution:** Treat cheque maturity/due date as `cheque_date` and
  expose it as Due Date where a due-oriented report requires that label.
- **Accounting Impact:** Post-dated maturity and forecasts use the same date as
  the lifecycle scheduler.
- **Technical Impact:** No duplicated or unsynchronized date field is added.
- **Decision Required:** A separate contractual due date would require an
  explicit schema and lifecycle change.

## 4. Bounced cheques must not be double-counted in exposure

- **Original Requirement:** Customer/Supplier exposure includes accounting
  balance, bounced cheques, outstanding cheque exposure, and total exposure.
- **Issue:** Bounce entries already restore the Customer receivable or Supplier
  payable. Adding bounced value again to total exposure double-counts it.
- **Recommended Solution:** Show bounced value as a risk column, but calculate
  total exposure as current AR/AP plus only live cheque obligations/assets.
- **Accounting Impact:** Exposure reconciles to economic position without
  counting the same obligation in both party ledger and cheque status.
- **Technical Impact:** Live inbound statuses are Post-Dated Held, Received, and
  Deposited; live outbound statuses are Post-Dated Held and Issued.
- **Decision Required:** The implementation uses the non-double-counting formula.

## 5. Cleared transactions are historical, not forecast cash flow

- **Original Requirement:** Forecast future inflows/outflows and exclude cleared
  transactions.
- **Issue:** Deposited inbound cheques remain future inflows until Clear, whereas
  bounced/cancelled/replaced/returned cheques are no longer valid forecasts.
- **Recommended Solution:** Include inbound Post-Dated Held, Received, and
  Deposited; include outbound Post-Dated Held and Issued. Exclude every terminal
  state. Past-due live cheques are placed in the first forecast period.
- **Accounting Impact:** Forecast reflects expected bank movement, not historical
  capture accounting.
- **Technical Impact:** Forecast period is based on `cheque_date` with configurable
  7/30/60/90/180-day horizons.
- **Decision Required:** The implementation uses these status definitions.

## 6. Historical “as of” reconstruction is limited by the source model

- **Original Requirement:** Date-filterable position and reconciliation reports.
- **Issue:** Current status fields alone cannot reconstruct a prior-period
  operational balance. Status changes are tracked in Version, but that log is not
  an accounting subledger and may be pruned.
- **Recommended Solution:** Reconciliation compares current operational state to
  current GL by default. A non-current `to_date` is allowed for GL investigation
  and clearly reported as a potential historical-snapshot limitation.
- **Accounting Impact:** Current-date reconciliation is authoritative; historical
  differences are exceptions to investigate rather than silently normalized.
- **Technical Impact:** Audit Trail reads Version plus linked accounting documents.
- **Decision Required:** A durable event ledger for exact historical snapshots is
  a separate data-model decision.

## 7. Persona names are mapped to existing ERPNext roles

- **Original Requirement:** Accountant, Finance Manager, CFO, and Owner /
  Management access tiers.
- **Issue:** Those exact roles are not installed by this app. It already grants
  cheque access through Accounts User, Cheque Manager, Accounts Manager, and
  System Manager.
- **Recommended Solution:** Operational reports allow Accounts User/Cheque
  Manager; management, exposure, forecast, and reconciliation reports allow
  Accounts Manager/System Manager, with Cheque Manager where operational access
  is required. All server functions still enforce document permissions.
- **Accounting Impact:** None.
- **Technical Impact:** No site-specific business roles are silently created.
- **Decision Required:** Sites may assign these standard roles to their named
  personas or add custom Role Profiles without changing report code.
