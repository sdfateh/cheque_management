import { ExternalLink } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import ConfirmDialog from "../ConfirmDialog";
import DateTimePicker from "../DateTimePicker";
import LinkField from "../LinkField";
import Money from "../Money";
import Select from "../Select";
import { Alert, Button, cx, inputCls } from "../ui";
import { api } from "../../lib/api";
import { __ } from "../../lib/i18n";
import { useUnsavedChanges } from "../../lib/useUnsavedChanges";

// Recording a cheque is the thing this desk does dozens of times a day, and the
// desk Payment Entry form asks for far more than a cheque needs. So the common
// path lives here - eight fields - and anything unusual opens the full form,
// which this dialog links to rather than trying to grow into.
//
// It still creates a real Payment Entry server-side: that is what writes the GL
// and what makes the MFG Cheque exist, so every desk validation still applies.

function Field({ label, children, hint }) {
	return (
		<label className="block">
			<span className="mb-1 flex items-baseline gap-1.5">
				<span className="text-xs font-medium text-content-muted">{label}</span>
				{hint && <span className="text-2xs text-content-faint">{hint}</span>}
			</span>
			{children}
		</label>
	);
}

export default function ChequeQuickEntry({ open, onClose, onCreated }) {
	const [meta, setMeta] = useState(null);
	const [form, setForm] = useState({});
	const [invoices, setInvoices] = useState([]);
	const [picked, setPicked] = useState([]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const firstRef = useRef(null);
	const { prompt, confirmDiscard, markSaved } = useUnsavedChanges(
		{ form, picked },
		{ enabled: open && Boolean(meta) }
	);
	const requestClose = useCallback(() => confirmDiscard(onClose), [confirmDiscard, onClose]);

	const set = (patch) => setForm((f) => ({ ...f, ...patch }));

	useEffect(() => {
		if (!open) return;
		setError("");
		setMeta(null);
		setForm({});
		setPicked([]);
		setInvoices([]);
		markSaved({ form: {}, picked: [] });
		api.cheques
			.quickEntry()
			.then((m) => {
				setMeta(m);
				const inbound = m.cheque_types.find((t) => t.name === m.default_inbound_type);
				const initial = {
					company: m.company,
					cheque_type: (inbound || m.cheque_types.find((t) => t.direction === "Inbound"))?.name,
					party_type: "Customer",
					cheque_date: m.today,
					posting_date: m.today,
					bank_account: m.default_bank_account,
				};
				setForm(initial);
				markSaved({ form: initial, picked: [] });
			})
			.catch((e) => setError(e.message));
	}, [open]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		if (open && meta) firstRef.current?.focus();
	}, [open, meta]);

	// The direction of the chosen type decides who the other party is.
	const direction = meta?.cheque_types.find((t) => t.name === form.cheque_type)?.direction || "Inbound";
	const partyType = direction === "Inbound" ? "Customer" : "Supplier";

	useEffect(() => {
		if (!open || !form.party || !form.company) return setInvoices([]);
		api.cheques
			.partyInvoices(partyType, form.party, form.company)
			.then(setInvoices)
			.catch(() => setInvoices([]));
	}, [open, form.party, form.company, partyType]);

	useEffect(() => {
		if (!open) return;
		function onKey(e) {
			if (e.key === "Escape" && !busy && !prompt) requestClose();
		}
		document.addEventListener("keydown", onKey);
		return () => document.removeEventListener("keydown", onKey);
	}, [open, busy, prompt, requestClose]);

	async function submit() {
		setBusy(true);
		setError("");
		try {
			const result = await api.cheques.createCapture({
				...form,
				party_type: partyType,
				invoices: picked,
			});
			onCreated?.(result);
			onClose();
		} catch (e) {
			setError(e.message);
		} finally {
			setBusy(false);
		}
	}

	if (!open) return null;

	const selectedTotal = invoices
		.filter((i) => picked.includes(i.name))
		.reduce((sum, i) => sum + Number(i.outstanding_amount || 0), 0);

	return (
		<>
			{createPortal(
				<div
					className="fixed inset-0 z-[10000] flex items-start justify-center overflow-auto bg-black/30 p-4 pt-[6vh]"
					onPointerDown={(e) => e.target === e.currentTarget && !busy && !prompt && requestClose()}
				>
			<div
				role="dialog"
				aria-modal="true"
				aria-label={__("Record a cheque")}
				className="animate-scale-in w-full max-w-2xl rounded-xl border border-border bg-surface shadow-lg"
			>
				<header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
					<div>
						<h2 className="text-sm font-semibold">{__("Record a cheque")}</h2>
						<p className="mt-0.5 text-xs text-content-muted">
							{__("Creates the Payment Entry that captures it.")}
						</p>
					</div>
					<a
						href="/app/payment-entry/new"
						className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
					>
						{__("Edit full details")}
						<ExternalLink size={12} />
					</a>
				</header>

				<div className="space-y-3 p-4">
					{error && <Alert tone="danger">{error}</Alert>}

					{!meta ? (
						<p className="py-6 text-center text-sm text-content-muted">{__("Loading…")}</p>
					) : (
						<>
							<div className="grid gap-3 sm:grid-cols-2">
								<Field label={__("Cheque Type")}>
									<Select
										ref={firstRef}
										value={form.cheque_type || ""}
										onChange={(v) => set({ cheque_type: v, party: undefined })}
										options={meta.cheque_types.map((t) => ({
											value: t.name,
											label: `${t.name} · ${__(t.direction)}`,
										}))}
										aria-label={__("Cheque Type")}
									/>
								</Field>

								<Field label={__(partyType)}>
									<LinkField
										doctype={partyType}
										className={inputCls}
										value={form.party || ""}
										placeholder={__("Search {0}…", [__(partyType)])}
										onChange={(v) => {
											set({ party: v });
											setPicked([]);
										}}
									/>
								</Field>

								<Field label={__("Cheque Number")}>
									<input
										className={inputCls}
										value={form.cheque_number || ""}
										onChange={(e) => set({ cheque_number: e.target.value })}
									/>
								</Field>

								<Field
									label={__("Cheque Date")}
									hint={__("A future date makes it post-dated")}
								>
									<DateTimePicker
										mode="date"
										size="compact"
										value={form.cheque_date || ""}
										onChange={(v) => set({ cheque_date: v })}
									/>
								</Field>

								<Field label={__("Amount")}>
									<input
										type="number"
										min="0"
										step="any"
										className={cx(inputCls, "text-end tabular-nums")}
										value={form.amount ?? ""}
										onChange={(e) => set({ amount: e.target.value })}
									/>
								</Field>

								{direction === "Inbound" && (
									<Field label={__("Drawee Bank")} hint={__("optional")}>
										<input
											className={inputCls}
											value={form.drawee_bank || ""}
											onChange={(e) => set({ drawee_bank: e.target.value })}
										/>
									</Field>
								)}
							</div>

							{invoices.length > 0 && (
								<div className="rounded-lg border border-border">
									<div className="flex items-center justify-between border-b border-border px-3 py-2">
										<span className="text-xs font-medium text-content-muted">
											{__("Settles")}
										</span>
										<span className="text-xs text-content-faint">
											{__("Allocated oldest first")}
										</span>
									</div>
									<div className="max-h-40 overflow-auto">
										{invoices.map((inv) => (
											<label
												key={inv.name}
												className="flex cursor-pointer items-center gap-2 border-b border-border/60 px-3 py-1.5 text-sm last:border-0 hover:bg-surface-2"
											>
												<input
													type="checkbox"
													className="h-3.5 w-3.5 accent-accent"
													checked={picked.includes(inv.name)}
													onChange={() =>
														setPicked((p) =>
															p.includes(inv.name)
																? p.filter((n) => n !== inv.name)
																: [...p, inv.name]
														)
													}
												/>
												<span className="grow truncate">{inv.name}</span>
												<span className="text-xs text-content-muted">{inv.due_date}</span>
												<span className="tabular-nums">
													<Money
														value={inv.outstanding_amount}
														currency={inv.currency}
														precision={meta.precision}
													/>
												</span>
											</label>
										))}
									</div>
									{picked.length > 0 && (
										<p className="border-t border-border px-3 py-1.5 text-xs text-content-muted">
											{__("Selected")}{" "}
											<Money
												value={selectedTotal}
												currency={meta.currency}
												precision={meta.precision}
											/>
											{Number(form.amount) > 0 && selectedTotal > Number(form.amount) && (
												<span className="ms-2 text-warning">
													{__("More than the cheque - the rest stays outstanding.")}
												</span>
											)}
										</p>
									)}
								</div>
							)}
						</>
					)}
				</div>

				<footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
					<Button variant="ghost" onClick={requestClose} disabled={busy}>
						{__("Cancel")}
					</Button>
					<Button
						variant="primary"
						busy={busy}
						disabled={!meta || !form.party || !form.amount || !form.cheque_number}
						onClick={submit}
					>
						{__("Record cheque")}
					</Button>
				</footer>
			</div>
				</div>,
				document.body
			)}
			<ConfirmDialog open={Boolean(prompt)} onConfirm={prompt?.onConfirm} onCancel={prompt?.onCancel} />
		</>
	);
}
