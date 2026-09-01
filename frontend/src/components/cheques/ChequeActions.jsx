import { useRef, useState } from "react";

import ConfirmDialog from "../ConfirmDialog";
import Money from "../Money";
import Select from "../Select";
import { Button, cx, inputCls } from "../ui";
import { api } from "../../lib/api";
import { __ } from "../../lib/i18n";
import { useUnsavedChanges } from "../../lib/useUnsavedChanges";
import { ACTION_LABEL, DESTRUCTIVE_ACTIONS } from "./statusTone";

// Every button here comes from the server's `allowed_actions`, which is derived
// from the same TRANSITIONS map the endpoints enforce. The SPA therefore cannot
// offer a move the server would reject - the list is never hard-coded here.

const CONFIRMATIONS = {
	mature: {
		title: "Mature this cheque?",
		message:
			"Moves it out of the post-dated account into the ordinary clearing account. No bank movement.",
	},
	deposit: {
		title: "Deposit this cheque?",
		message:
			"Records that the cheque is with the bank for collection. Your bank balance does not change until it clears.",
	},
	clear: {
		title: "Clear this cheque?",
		message: "This is the step that moves real money in your bank account.",
	},
		bounce: {
		title: "Bounce this cheque?",
		message:
			"Restores the party balance in one step. For an inbound cheque, it also reverses the deposit. Record any bank fee below.",
	},
	return_to_party: {
		title: "Return this cheque to the customer?",
		message: "Records the physical handover only. The accounting was already restored when it bounced.",
	},
	replace: {
		title: "Start a replacement cheque?",
		message:
			"Opens a draft Payment Entry for the new cheque. Nothing is posted until you submit that entry.",
	},
};

export default function ChequeActions({
	cheque,
	allowedActions,
	feeTreatments,
	defaultFeeTreatment,
	onDone,
}) {
	const [pending, setPending] = useState(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [fee, setFee] = useState({
		amount: "",
		treatment: defaultFeeTreatment || "Company Expense",
		partyShare: "",
		reason: "",
	});
	const feeRef = useRef(null);
	const { prompt, confirmDiscard, markSaved } = useUnsavedChanges(fee, {
		enabled: pending === "bounce",
	});

	function openAction(action) {
		setError("");
		if (action === "bounce") {
			const initial = {
				amount: "",
				treatment: defaultFeeTreatment || "Company Expense",
				partyShare: "",
				reason: "",
			};
			setFee(initial);
			markSaved(initial);
		}
		setPending(action);
	}

	const closeAction = () => confirmDiscard(() => setPending(null));

	async function run(action) {
		setBusy(true);
		setError("");
		try {
			let result;
			if (action === "bounce") {
				result = await api.cheques.bounce(cheque.name, {
					fee_amount: Number(fee.amount) || 0,
					fee_treatment: fee.treatment,
					party_share: Number(fee.partyShare) || 0,
					reason: fee.reason,
				});
			} else if (action === "replace") {
				result = await api.cheques.replace(cheque.name);
				// The replacement is captured on the desk Payment Entry form, which
				// is where cheque details belong; nothing is posted until it is
				// submitted there.
				window.location.href = `/app/payment-entry/${result.payment_entry}`;
				return;
			} else {
				result = await api.cheques[action === "return_to_party" ? "returnToParty" : action](
					cheque.name
				);
			}
			setPending(null);
			onDone?.(result);
		} catch (e) {
			setError(e.message);
		} finally {
			setBusy(false);
		}
	}

	if (!allowedActions?.length) return null;

	return (
		<>
			<div className="flex flex-wrap items-center gap-2">
				{allowedActions.map((action) => (
					<Button
						key={action}
						variant={DESTRUCTIVE_ACTIONS.has(action) ? "danger" : "primary"}
						onClick={() => openAction(action)}
					>
						{__(ACTION_LABEL[action] || action)}
					</Button>
				))}
			</div>

			<ConfirmDialog
				open={!!pending}
				danger={DESTRUCTIVE_ACTIONS.has(pending)}
				title={__(CONFIRMATIONS[pending]?.title || "Are you sure?")}
				message={__(CONFIRMATIONS[pending]?.message || "")}
				confirmLabel={busy ? __("Working…") : __(ACTION_LABEL[pending] || "Confirm")}
				cancelLabel={__("Cancel")}
				initialFocusRef={pending === "bounce" ? feeRef : undefined}
				onConfirm={() => !busy && run(pending)}
				onCancel={prompt ? undefined : () => !busy && closeAction()}
			>
				{pending === "bounce" && (
					<div className="mt-3 space-y-3 text-sm">
						<label className="block">
							<span className="text-content-muted">{__("Bank fee")}</span>
							<input
								ref={feeRef}
								type="number"
								min="0"
								step="0.001"
								value={fee.amount}
								onChange={(e) => setFee({ ...fee, amount: e.target.value })}
								className={cx(inputCls, "mt-1")}
							/>
						</label>

						{Number(fee.amount) > 0 && (
							<label className="block">
								<span className="text-content-muted">{__("Who pays it")}</span>
								<Select
									className="mt-1"
									value={fee.treatment}
									onChange={(v) => setFee({ ...fee, treatment: v })}
									options={feeTreatments || []}
									aria-label={__("Who pays it")}
								/>
							</label>
						)}

						{fee.treatment === "Split" && Number(fee.amount) > 0 && (
							<label className="block">
								<span className="text-content-muted">
									{__("Share recharged to the party")}
								</span>
								<input
									type="number"
									min="0"
									step="0.001"
									value={fee.partyShare}
									onChange={(e) => setFee({ ...fee, partyShare: e.target.value })}
									className={cx(inputCls, "mt-1")}
								/>
							</label>
						)}

						<label className="block">
							<span className="text-content-muted">{__("Reason")}</span>
							<input
								type="text"
								value={fee.reason}
								onChange={(e) => setFee({ ...fee, reason: e.target.value })}
								className={cx(inputCls, "mt-1")}
							/>
						</label>

						<p className="text-content-muted">
							{__(
								cheque.direction === "Inbound"
									? "The customer will be re-debited"
									: "The supplier will be re-credited"
							)}{" "}
							<Money value={cheque.amount} currency={cheque.currency} />
						</p>
					</div>
				)}

				{error && <p className="mt-3 text-sm text-danger">{error}</p>}
			</ConfirmDialog>
			<ConfirmDialog open={Boolean(prompt)} onConfirm={prompt?.onConfirm} onCancel={prompt?.onCancel} />
		</>
	);
}
