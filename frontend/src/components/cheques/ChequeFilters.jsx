import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import DateTimePicker from "../DateTimePicker";
import LinkField from "../LinkField";
import Select from "../Select";
import { Button, cx, inputCls } from "../ui";
import { __ } from "../../lib/i18n";

// One row above the data, per the usual reading order: narrow the set, then read
// it. Everything here maps to a filter the server actually honours - there is no
// client-side filtering, so what you see is what was queried.
//
// Every control wears `inputCls`, including the LinkField: it applies only the
// caller's className, so leaving it off renders a bare browser input that sits
// taller than its neighbours and ignores the theme.
//
// Widths are sized to the longest value each control actually shows, not to a
// tidy-looking grid: a truncated "Aug 3, 2..." or "Returned to Cus..." makes the
// user open the control just to read what is already selected. The row wraps
// instead of shrinking its fields.
//
// Dates go through the app's own DateTimePicker rather than <input type="date">:
// the native control opens only on its small glyph, renders in the browser's
// locale rather than the user's, and cannot be themed - it stays stubbornly
// light in dark mode.

const STATUSES = [
	"Post-Dated Held",
	"Received",
	"Issued",
	"Deposited",
	"Cleared",
	"Bounced",
	"Returned to Customer",
	"Replaced",
	"Cancelled",
];

export default function ChequeFilters({ value, onChange, onReset, busy }) {
	// Typing should not fire a query per keystroke; the rest apply immediately.
	const [search, setSearch] = useState(value.search || "");
	useEffect(() => setSearch(value.search || ""), [value.search]);
	useEffect(() => {
		const id = setTimeout(() => {
			if ((value.search || "") !== search) onChange({ ...value, search });
		}, 300);
		return () => clearTimeout(id);
	}, [search]); // eslint-disable-line react-hooks/exhaustive-deps

	const set = (patch) => onChange({ ...value, ...patch });
	const active = Object.entries(value).some(
		([k, v]) => k !== "company" && v !== "" && v != null
	);

	return (
		<div className="flex flex-wrap items-center gap-2">
			<div className="relative w-56">
				<Search
					size={14}
					className="pointer-events-none absolute inset-y-0 start-2.5 z-10 my-auto text-content-faint"
				/>
				<input
					type="search"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					placeholder={__("Cheque no., party, bank…")}
					className={cx(inputCls, "ps-8")}
					aria-label={__("Search cheques")}
				/>
			</div>

			<Select
				className="w-52"
				value={value.status || ""}
				onChange={(v) => set({ status: v || undefined, overdue: undefined })}
				options={STATUSES}
				placeholder={__("Any status")}
				aria-label={__("Status")}
			/>

			<Select
				className="w-44"
				value={value.direction || ""}
				onChange={(v) => set({ direction: v || undefined })}
				options={["Inbound", "Outbound"]}
				placeholder={__("Both directions")}
				aria-label={__("Direction")}
			/>

			<div className="flex items-center gap-1.5">
				<div className="w-48">
					<DateTimePicker
						mode="date"
						size="compact"
						value={value.from_date || ""}
						onChange={(v) => set({ from_date: v || undefined })}
						max={value.to_date || undefined}
						placeholder={__("From")}
					/>
				</div>
				<span className="text-xs text-content-faint rtl:rotate-180">→</span>
				<div className="w-48">
					<DateTimePicker
						mode="date"
						size="compact"
						value={value.to_date || ""}
						onChange={(v) => set({ to_date: v || undefined })}
						min={value.from_date || undefined}
						placeholder={__("To")}
					/>
				</div>
			</div>

			<div className="w-48">
				<LinkField
					doctype="Customer"
					className={inputCls}
					value={value.party || ""}
					placeholder={__("Any party")}
					onChange={(v) => set({ party: v || undefined })}
				/>
			</div>

			{active && (
				<Button variant="ghost" icon={X} onClick={onReset} disabled={busy}>
					{__("Clear")}
				</Button>
			)}
		</div>
	);
}
