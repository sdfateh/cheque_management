# Cheque Management Agent Rules

These instructions apply to the entire repository.

## Required shared rules

- Before planning or changing this app, read `../sanawbar/CLAUDE.md` completely
  and apply its cross-application rules.
- The Sanawbar rules are mandatory; this file adds cheque-specific constraints.
  If the two files appear to conflict, stop and ask the user rather than
  weakening either rule.
- For UI work, read `../sanawbar/design-rules/README.md` and the relevant linked
  rules before implementation.

## Cheque Management ownership

- This app independently owns cheque DocTypes, lifecycle APIs, accounting
  hooks, scheduler jobs, permissions, translations, and the `/cheques` SPA.
- Never import `mfg_suite`. Shared behavior must come from `sanawbar`; cheque
  domain behavior stays here.
- Preserve the existing `MFG Cheque*` DocType names and database tables unless
  the user explicitly approves a separately planned data migration.

## Accounting integrity

- Lifecycle actions must create and cancel standard Payment Entries and Journal
  Entries through their controllers. Never write directly to GL Entry or treat
  a status change as an accounting action.
- The server transition map and `allowed_actions` response are authoritative.
  The SPA must not invent transitions or use client visibility as enforcement.
- Preserve row locking and idempotency guards around lifecycle actions. Bulk and
  scheduled processing must isolate failures without silently duplicating
  accounting entries.
- Keep cheque account validation strict: clearing ledgers, bank accounts,
  company, direction, party, currency, and posting periods must agree before
  posting.

## Frontend boundaries

- Consume the shell, theme, controls, and generic utilities from
  `@sanawbar/core`. App-local wrappers may inject permission-scoped cheque APIs.
- Keep cheque labels and server messages in the cheque translation catalogue;
  generic strings belong in Sanawbar.

## Permissions and verification

- Every endpoint must enforce the required Cheque Manager and DocType/document
  permissions on the server.
- Lifecycle tests must assert both cheque state and the accounting entries
  produced. Run frontend lint, Python checks, and the production cheque build
  for changes that affect the SPA or shared integration.
