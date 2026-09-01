import { AlertTriangle, Banknote, CalendarClock, Landmark, XCircle } from "lucide-react";

import Money from "../Money";
import { Card, Skeleton, StatTile, cx } from "../ui";
import { __ } from "../../lib/i18n";

// Two questions run cheque management: how much is in flight and where, and what
// is about to need attention. The tiles answer the first, the maturity profile
// the second. Neither is a decoration - each one is a filter you can click.

const TILES = [
	{ key: "in_hand", label: "In Hand", icon: Banknote, filter: { status: "Received" } },
	{
		key: "under_collection",
		label: "With the Bank",
		icon: Landmark,
		filter: { status: "Deposited" },
	},
	{
		key: "post_dated",
		label: "Post-Dated",
		icon: CalendarClock,
		filter: { status: "Post-Dated Held" },
	},
	{
		key: "overdue",
		label: "Overdue",
		icon: AlertTriangle,
		tone: "danger",
		filter: { overdue: 1 },
	},
	{ key: "bounced", label: "Bounced", icon: XCircle, tone: "danger", filter: { status: "Bounced" } },
];

function BucketBars({ buckets, currency, precision }) {
	const max = Math.max(...buckets.map((b) => b.amount), 0);
	if (!buckets.length) {
		return <p className="text-sm text-content-muted">{__("Nothing outstanding.")}</p>;
	}

	return (
		<div className="space-y-2.5">
			{buckets.map((bucket) => {
				// A single measure across named groups: one hue carries magnitude, and
				// the width IS the comparison. Overdue is the exception - a state, not
				// a bigger number - so it takes the alert colour and an icon.
				const overdue = bucket.label === "Overdue";
				const pct = max ? Math.max((bucket.amount / max) * 100, 1.5) : 0;

				return (
					<div key={bucket.label} className="grid grid-cols-[9rem,1fr,auto] items-center gap-3">
						<span
							className={cx(
								"flex items-center gap-1 truncate text-xs",
								overdue ? "text-danger" : "text-content-muted"
							)}
							title={__(bucket.label)}
						>
							{overdue && <AlertTriangle size={12} />}
							{__(bucket.label)}
						</span>

						{/* Track is recessive; the mark carries the ink. Rounded data-end,
						    anchored at the baseline (the start edge). */}
						<span className="relative block h-3 rounded-sm bg-surface-3" aria-hidden="true">
							<span
								className={cx(
									"absolute inset-y-0 start-0 rounded-e-[4px]",
									overdue ? "bg-chart-alert" : "bg-chart-bar"
								)}
								style={{ width: `${pct}%` }}
							/>
						</span>

						<span className="whitespace-nowrap text-xs tabular-nums text-content">
							<Money value={bucket.amount} currency={currency} precision={precision} />
							<span className="ms-2 text-content-faint">{bucket.count}</span>
						</span>
					</div>
				);
			})}
		</div>
	);
}

export default function ChequeStats({ data, loading, activeTile, onTile }) {
	if (loading) {
		return (
			<div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
				{TILES.map((t) => (
					<Skeleton key={t.key} className="h-20 w-full" />
				))}
			</div>
		);
	}
	if (!data) return null;

	const { kpis, buckets, currency, precision } = data;

	return (
		<div className="space-y-4">
			<div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
				{TILES.map(({ key, label, icon, tone, filter }) => {
					const kpi = kpis[key] || { count: 0, amount: 0 };
					return (
						<StatTile
							key={key}
							label={__(label)}
							icon={icon}
							tone={kpi.count ? tone || "neutral" : "neutral"}
							value={<Money value={kpi.amount} currency={currency} precision={precision} />}
							sub={__("{0} cheques", [kpi.count])}
							active={activeTile === key}
							onClick={() => onTile(activeTile === key ? null : key, filter)}
						/>
					);
				})}
			</div>

			<Card
				title={__("Maturity profile")}
				description={__("Outstanding cheques by when they fall due, in company currency.")}
			>
				<BucketBars buckets={buckets} currency={currency} precision={precision} />
			</Card>
		</div>
	);
}

export { TILES };
