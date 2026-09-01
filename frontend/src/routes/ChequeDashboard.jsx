import {
	ArrowRight,
	Banknote,
	CalendarClock,
	FilePlus2,
	Landmark,
	ListChecks,
	Settings,
	Tags,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ChequeQuickEntry from "../components/cheques/ChequeQuickEntry";
import ChequeStats from "../components/cheques/ChequeStats";
import Money from "../components/Money";
import { Alert, Badge, Card, PageHeader, Skeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { __ } from "../lib/i18n";
import { statusTone } from "../components/cheques/statusTone";

// The landing screen answers "what needs me today", and every number on it is a
// door: clicking a tile or a shortcut opens the list already filtered, so nobody
// has to rebuild the same query by hand.

// Capture happens on a Payment Entry - that is what creates the GL - so "record a
// cheque" deliberately hands over to the desk form rather than pretending the SPA
// can book one.
const SHORTCUTS = [
	{
		label: "Record a cheque",
		hint: "Capture it here, without leaving the page",
		icon: FilePlus2,
		action: "capture",
		primary: true,
	},
	{
		label: "To deposit",
		hint: "In hand, waiting to go to the bank",
		icon: Landmark,
		to: "/list?status=Received",
	},
	{
		label: "Awaiting clearance",
		hint: "With the bank, not yet cleared",
		icon: ListChecks,
		to: "/list?status=Deposited",
	},
	{
		label: "Post-dated diary",
		hint: "Held until their date arrives",
		icon: CalendarClock,
		to: "/list?status=Post-Dated Held",
	},
	{ label: "Cheque types", hint: "Clearing accounts per company", icon: Tags, href: "/app/mfg-cheque-type" },
	{
		label: "Settings",
		hint: "Bank charges, default accounts",
		icon: Settings,
		href: "/app/mfg-cheque-settings",
	},
];

function Shortcut({ label, hint, icon: Icon, to, href, onClick, primary }) {
	const className = cx(
		"group flex items-start gap-3 rounded-xl border p-3 text-start transition-colors",
		primary
			? "border-accent bg-accent-soft hover:brightness-95 dark:hover:brightness-125"
			: "border-border bg-surface hover:border-border-strong"
	);
	const body = (
		<>
			<span
				className={cx(
					"mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
					primary ? "bg-accent text-accent-fg" : "bg-surface-3 text-content-muted"
				)}
			>
				<Icon size={15} />
			</span>
			<span className="min-w-0">
				<span className="flex items-center gap-1 text-sm font-medium">
					{__(label)}
					<ArrowRight
						size={13}
						className="opacity-0 transition-opacity group-hover:opacity-60 rtl:rotate-180"
					/>
				</span>
				<span className="mt-0.5 block text-xs text-content-muted">{__(hint)}</span>
			</span>
		</>
	);

	if (onClick) {
		return (
			<button type="button" onClick={onClick} className={className}>
				{body}
			</button>
		);
	}
	return href ? (
		<a href={href} className={className}>
			{body}
		</a>
	) : (
		<Link to={to} className={className}>
			{body}
		</Link>
	);
}

function AttentionRow({ cheque }) {
	return (
		<Link
			to={`/list?search=${encodeURIComponent(cheque.cheque_number)}`}
			className="flex items-center justify-between gap-3 border-b border-border/60 py-2 text-sm last:border-0 hover:bg-surface-3"
		>
			<span className="min-w-0">
				<span className="font-medium">{cheque.cheque_number}</span>
				<span className="ms-2 text-content-muted">{cheque.party}</span>
			</span>
			<span className="flex shrink-0 items-center gap-2">
				<span className="tabular-nums">
					<Money value={cheque.amount} currency={cheque.currency} />
				</span>
				<Badge tone={statusTone(cheque.status)}>{__(cheque.status)}</Badge>
			</span>
		</Link>
	);
}

export default function ChequeDashboard() {
	const navigate = useNavigate();
	const [stats, setStats] = useState(null);
	const [attention, setAttention] = useState([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");
	const [capturing, setCapturing] = useState(false);
	const [notice, setNotice] = useState(null);

	const load = useCallback(async () => {
		setLoading(true);
		setError("");
		try {
			const [dashboard, overdue, bounced] = await Promise.all([
				api.cheques.dashboard({}),
				api.cheques.list({ overdue: 1 }, { limit: 5, order_by: "cheque_date" }),
				api.cheques.list({ status: "Bounced" }, { limit: 5, order_by: "cheque_date", order_dir: "desc" }),
			]);
			setStats(dashboard);
			setAttention([...overdue.rows, ...bounced.rows]);
		} catch (e) {
			setError(e.message);
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		load();
	}, [load]);

	// A tile is a saved query: it opens the list with that filter already applied.
	function onTile(key, filter) {
		if (!key) return;
		const params = new URLSearchParams(
			Object.entries(filter).map(([k, v]) => [k, String(v)])
		);
		navigate(`/list?${params.toString()}`);
	}

	return (
		<div className="mx-auto max-w-[1440px] px-4 py-6">
			<PageHeader
				title={__("Cheque Management")}
				description={__("What is in flight, what falls due, and what needs attention today.")}
			/>

			{error && (
				<Alert tone="danger" action={{ label: __("Retry"), onClick: load }}>
					{error}
				</Alert>
			)}

			{notice && (
				<div className="mt-3">
					<Alert tone="success">
						{__("Cheque {0} recorded.", [notice.cheque || ""])}{" "}
						<a className="underline" href={`/app/payment-entry/${notice.payment_entry}`}>
							{__("Edit full details")}
						</a>
					</Alert>
				</div>
			)}

			<div className="mt-4">
				<ChequeStats data={stats} loading={loading} activeTile={null} onTile={onTile} />
			</div>

			<div className="mt-4 grid gap-4 lg:grid-cols-3">
				<div className="lg:col-span-2">
					<Card
						title={__("Shortcuts")}
						description={__("The things a cheque desk does every day.")}
					>
						<div className="grid gap-2.5 sm:grid-cols-2">
							{SHORTCUTS.map((s) => (
								<Shortcut
									key={s.label}
									{...s}
									onClick={s.action === "capture" ? () => setCapturing(true) : undefined}
								/>
							))}
						</div>
					</Card>
				</div>

				<Card
					title={__("Needs attention")}
					description={__("Overdue with the bank, and anything that bounced.")}
					action={
						<Link to="/list" className="text-sm text-accent hover:underline">
							{__("All cheques")}
						</Link>
					}
				>
					{loading ? (
						<div className="space-y-2">
							{[0, 1, 2].map((i) => (
								<Skeleton key={i} className="h-8 w-full" />
							))}
						</div>
					) : attention.length ? (
						<div>
							{attention.map((c) => (
								<AttentionRow key={c.name} cheque={c} />
							))}
						</div>
					) : (
						<p className="flex items-center gap-2 text-sm text-content-muted">
							<Banknote size={15} />
							{__("Nothing overdue or bounced.")}
						</p>
					)}
				</Card>
			</div>
			<ChequeQuickEntry
				open={capturing}
				onClose={() => setCapturing(false)}
				onCreated={(result) => {
					setNotice(result);
					load();
				}}
			/>
		</div>
	);
}
