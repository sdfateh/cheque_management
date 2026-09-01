import { ArrowDown, ArrowUp, CalendarClock } from "lucide-react";

import Money from "../Money";
import { Badge, EmptyState, Skeleton, cx } from "../ui";
import { __ } from "../../lib/i18n";
import { statusTone } from "./statusTone";

// A cheque list is read as a diary, not a ledger: what is due, from whom, for how
// much. So it sorts by cheque date and leads with the date, not the id.

const COLUMNS = [
	{ key: "cheque_date", label: "Cheque Date", sortable: true },
	{ key: "cheque_number", label: "Cheque Number", sortable: true },
	{ key: "party", label: "Party", sortable: true },
	{ key: "amount", label: "Amount", sortable: true, align: "end" },
	{ key: "status", label: "Status", sortable: true },
];

export function isOverdue(cheque) {
	return (
		cheque.status === "Deposited" &&
		cheque.cheque_date &&
		new Date(cheque.cheque_date) < new Date(new Date().toDateString())
	);
}

export default function ChequeTable({
	cheques,
	loading,
	selected,
	onSelect,
	checked = [],
	onCheck,
	sort,
	onSort,
	precision,
}) {
	if (loading) {
		return (
			<div className="space-y-2 p-3">
				{[0, 1, 2, 3, 4].map((i) => (
					<Skeleton key={i} className="h-11 w-full" />
				))}
			</div>
		);
	}

	if (!cheques.length) {
		return (
			<div className="p-4">
				<EmptyState
					icon={CalendarClock}
					title={__("No cheques here")}
					description={__("Try widening the filters, or clear them to see everything.")}
				/>
			</div>
		);
	}

	// Only cheques that can actually be deposited are selectable - offering a
	// checkbox that leads to a refusal is worse than offering nothing.
	const selectable = cheques.filter((c) => c.status === "Received").map((c) => c.name);
	const allChecked = selectable.length > 0 && selectable.every((n) => checked.includes(n));

	return (
		<div className="overflow-x-auto">
			<table className="w-full text-sm">
				<thead className="text-content-muted">
					<tr className="border-b border-border">
						<th className="w-9 px-3 py-2">
							{selectable.length > 0 && (
								<input
									type="checkbox"
									checked={allChecked}
									onChange={() => onCheck(allChecked ? [] : selectable)}
									aria-label={__("Select all depositable cheques")}
									className="h-3.5 w-3.5 accent-accent"
								/>
							)}
						</th>
						{COLUMNS.map(({ key, label, sortable, align }) => (
							<th
								key={key}
								className={cx("px-3 py-2 font-medium", align === "end" ? "text-end" : "text-start")}
							>
								{sortable ? (
									<button
										type="button"
										onClick={() => onSort(key)}
										className="inline-flex items-center gap-1 hover:text-content"
									>
										{__(label)}
										{sort?.by === key &&
											(sort.dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
									</button>
								) : (
									__(label)
								)}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{cheques.map((cheque) => {
						const overdue = isOverdue(cheque);
						const canCheck = cheque.status === "Received";

						return (
							<tr
								key={cheque.name}
								onClick={() => onSelect(cheque.name)}
								className={cx(
									"cursor-pointer border-b border-border/60 transition-colors hover:bg-surface-3",
									selected === cheque.name && "bg-accent-soft"
								)}
							>
								<td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
									{canCheck && (
										<input
											type="checkbox"
											checked={checked.includes(cheque.name)}
											onChange={() =>
												onCheck(
													checked.includes(cheque.name)
														? checked.filter((n) => n !== cheque.name)
														: [...checked, cheque.name]
												)
											}
											aria-label={__("Select {0}", [cheque.cheque_number])}
											className="h-3.5 w-3.5 accent-accent"
										/>
									)}
								</td>

								<td className="whitespace-nowrap px-3 py-2">
									<span className={cx(overdue && "font-medium text-danger")}>
										{cheque.cheque_date}
									</span>
									{cheque.is_post_dated ? (
										<span className="ms-2 text-xs text-content-muted">{__("post-dated")}</span>
									) : null}
								</td>

								<td className="px-3 py-2 font-medium">{cheque.cheque_number}</td>

								<td className="px-3 py-2">
									<div>{cheque.party}</div>
									{cheque.drawee_bank && (
										<div className="text-xs text-content-muted">{cheque.drawee_bank}</div>
									)}
								</td>

								<td className="whitespace-nowrap px-3 py-2 text-end tabular-nums">
									<Money value={cheque.amount} currency={cheque.currency} precision={precision} />
								</td>

								<td className="px-3 py-2">
									<Badge tone={statusTone(cheque.status)}>{__(cheque.status)}</Badge>
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}
