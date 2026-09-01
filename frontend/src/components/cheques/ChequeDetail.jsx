import { ExternalLink } from "lucide-react";

import Money from "../Money";
import { Alert, Badge, Card, Spinner } from "../ui";
import { __ } from "../../lib/i18n";
import ChequeActions from "./ChequeActions";
import { statusTone } from "./statusTone";

// The detail pane exists to answer two questions: where is this cheque, and what
// can I do about it. The entry trail is deliberately visible - every lifecycle
// step is a real Journal Entry or Payment Entry, and an accountant will want to
// open them.

const ENTRY_LINKS = [
	["maturity_journal_entry", "Maturity", "journal-entry"],
	["deposit_journal_entry", "Deposit", "journal-entry"],
	["deposit_reversal_journal_entry", "Deposit Reversal", "journal-entry"],
	["clear_payment_entry", "Clear", "payment-entry"],
	["bounce_journal_entry", "Bounce", "journal-entry"],
	["bounce_fee_journal_entry", "Bank Fee", "journal-entry"],
	["source_payment_entry", "Capture", "payment-entry"],
];

function Row({ label, children }) {
	return (
		<div className="flex items-baseline justify-between gap-4 py-1.5">
			<span className="text-content-muted">{__(label)}</span>
			<span className="text-end">{children}</span>
		</div>
	);
}

export default function ChequeDetail({ detail, loading, onChanged }) {
	if (loading) {
		return (
			<div className="flex items-center justify-center p-10">
				<Spinner />
			</div>
		);
	}
	if (!detail) return null;

	const cheque = detail.cheque;

	return (
		<div className="space-y-4">
			<Card
				title={cheque.cheque_number}
				description={`${__(cheque.direction)} · ${cheque.cheque_type}`}
				action={
					<div className="flex items-center gap-2">
						<Badge tone={statusTone(cheque.status)}>{__(cheque.status)}</Badge>
						{/* The lifecycle lives here; everything else about the record -
						    dimensions, comments, the full audit trail - lives in the desk
						    form, which is one click away rather than duplicated. */}
						<a
							href={`/app/mfg-cheque/${cheque.name}`}
							className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-accent hover:underline"
						>
							{__("Edit full details")}
							<ExternalLink size={12} />
						</a>
					</div>
				}
			>
				<div className="divide-y divide-border/60 text-sm">
					<Row label="Party">{cheque.party}</Row>
					<Row label="Amount">
						<Money
							value={cheque.amount}
							currency={cheque.currency}
							precision={detail.currency_precision}
						/>
					</Row>
					<Row label="Cheque Date">{cheque.cheque_date}</Row>
					{cheque.drawee_bank && <Row label="Drawee Bank">{cheque.drawee_bank}</Row>}
					{cheque.bank_account && <Row label="Bank Account">{cheque.bank_account}</Row>}
					{cheque.bounce_date && <Row label="Bounce Date">{cheque.bounce_date}</Row>}
					{cheque.bounce_reason && <Row label="Reason">{cheque.bounce_reason}</Row>}
					{cheque.fee_amount ? (
						<Row label="Bank Fee">
							<Money value={cheque.fee_amount} currency={cheque.currency} />
							<span className="ms-2 text-content-muted">{__(cheque.fee_treatment)}</span>
						</Row>
					) : null}
					{cheque.returned_on && <Row label="Returned On">{cheque.returned_on}</Row>}
					{cheque.replaced_by && <Row label="Replaced By">{cheque.replaced_by}</Row>}
					{cheque.replaces && <Row label="Replaces">{cheque.replaces}</Row>}
				</div>
			</Card>

			{cheque.status === "Bounced" && (
				<Alert tone="danger">
					{__("The party balance has been restored. Hand the cheque back, then record a replacement.")}
				</Alert>
			)}

			{cheque.deposit_reversal_method === "Dated Reversal" && (
				<Alert tone="warning">
					{__(
						"The original deposit period was closed, so the reversal was posted on the bounce date instead of cancelling the deposit."
					)}
				</Alert>
			)}

			{detail.can_write && (
				<ChequeActions
					cheque={cheque}
					allowedActions={detail.allowed_actions}
					feeTreatments={detail.fee_treatments}
					defaultFeeTreatment={detail.default_fee_treatment}
					onDone={onChanged}
				/>
			)}

			{cheque.allocations?.length > 0 && (
				<Card title={__("Settles")}>
					<div className="divide-y divide-border/60 text-sm">
						{cheque.allocations.map((a) => (
							<Row key={a.name} label={a.reference_name}>
								<Money value={a.allocated_amount} currency={cheque.currency} />
							</Row>
						))}
					</div>
				</Card>
			)}

			<Card
				title={__("Accounting Entries")}
				description={__("Every step is a standard entry. Nothing here writes to the ledger directly.")}
			>
				<div className="divide-y divide-border/60 text-sm">
					{ENTRY_LINKS.filter(([field]) => cheque[field]).map(([field, label, route]) => (
						<Row key={field} label={label}>
							<a
								className="inline-flex items-center gap-1 text-accent hover:underline"
								href={`/app/${route}/${cheque[field]}`}
							>
								{cheque[field]}
								<ExternalLink size={13} />
							</a>
						</Row>
					))}
				</div>
			</Card>
		</div>
	);
}
