import { Download, Landmark } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import ChequeDetail from "../components/cheques/ChequeDetail";
import ChequeFilters from "../components/cheques/ChequeFilters";
import ChequeTable from "../components/cheques/ChequeTable";
import ConfirmDialog from "../components/ConfirmDialog";
import { Alert, Button, Card, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { __ } from "../lib/i18n";

// Cheque management is mostly "what is due, and what is stuck", so the screen
// opens on outstanding cheques by date. Everything narrows the same server-side
// query: the tiles, the filter row and the table all read one filter object, so
// the headline numbers and the rows on screen can never describe different sets.

const PAGE_SIZE = 50;
const DEFAULT_FILTERS = { outstanding: 1 };

// Filters live in the URL so a tile, a shortcut or a colleague's link all land on
// the same view, and the browser's back button undoes a filter change.
const URL_KEYS = [
	"status",
	"direction",
	"party",
	"search",
	"from_date",
	"to_date",
	"overdue",
	"outstanding",
	"min_amount",
	"max_amount",
];

function filtersFromUrl(params) {
	const out = {};
	for (const key of URL_KEYS) {
		const value = params.get(key);
		if (value !== null && value !== "") out[key] = value;
	}
	return Object.keys(out).length ? out : DEFAULT_FILTERS;
}

function urlFromFilters(filters) {
	const params = new URLSearchParams();
	for (const key of URL_KEYS) {
		const value = filters[key];
		if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
	}
	return params;
}

function toCsv(rows) {
	const cols = [
		"cheque_number",
		"cheque_date",
		"status",
		"direction",
		"party",
		"amount",
		"currency",
		"drawee_bank",
		"bank_account",
	];
	const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
	return [cols.join(","), ...rows.map((r) => cols.map((c) => escape(r[c])).join(","))].join("\n");
}

export default function Cheques() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [filters, setFilters] = useState(() => filtersFromUrl(searchParams));
	const [sort, setSort] = useState({ by: "cheque_date", dir: "asc" });
	const [page, setPage] = useState(0);

	const [list, setList] = useState({ rows: [], total: 0 });
	const [loading, setLoading] = useState(true);

	const [selected, setSelected] = useState(null);
	const [detail, setDetail] = useState(null);
	const [detailLoading, setDetailLoading] = useState(false);

	const [checked, setChecked] = useState([]);
	const [bulkOpen, setBulkOpen] = useState(false);
	const [bulkBusy, setBulkBusy] = useState(false);
	const [notice, setNotice] = useState(null);
	const [error, setError] = useState("");

	const query = useMemo(() => ({ ...filters }), [filters]);

	const loadList = useCallback(async () => {
		setLoading(true);
		setError("");
		try {
			setList(
				await api.cheques.list(query, {
					limit: PAGE_SIZE,
					start: page * PAGE_SIZE,
					order_by: sort.by,
					order_dir: sort.dir,
				})
			);
		} catch (e) {
			setError(e.message);
		} finally {
			setLoading(false);
		}
	}, [query, page, sort]);

	useEffect(() => {
		loadList();
	}, [loadList]);

	const loadDetail = useCallback(async (name) => {
		if (!name) return setDetail(null);
		setDetailLoading(true);
		try {
			setDetail(await api.cheques.get(name));
		} catch (e) {
			setError(e.message);
		} finally {
			setDetailLoading(false);
		}
	}, []);

	useEffect(() => {
		loadDetail(selected);
	}, [selected, loadDetail]);

	// A lifecycle action moves money, so every view of it refreshes - the row, the
	// pane and the headline numbers.
	async function refreshAll() {
		setChecked([]);
		await Promise.all([loadList(), loadDetail(selected)]);
	}

	function applyFilters(next) {
		setPage(0);
		setFilters(next);
		setSearchParams(urlFromFilters(next), { replace: true });
	}

	function onSort(by) {
		setPage(0);
		setSort((s) => ({ by, dir: s.by === by && s.dir === "asc" ? "desc" : "asc" }));
	}

	async function runBulkDeposit() {
		setBulkBusy(true);
		try {
			const result = await api.cheques.bulkDeposit(checked);
			setBulkOpen(false);
			setNotice(
				result.failed.length
					? {
							tone: "warning",
							text: __("Deposited {0}, failed {1}: {2}", [
								result.deposited.length,
								result.failed.length,
								result.failed.map((f) => `${f.cheque} (${f.error})`).join("; "),
							]),
						}
					: { tone: "success", text: __("Deposited {0} cheques.", [result.deposited.length]) }
			);
			await refreshAll();
		} catch (e) {
			setError(e.message);
		} finally {
			setBulkBusy(false);
		}
	}

	function exportCsv() {
		const blob = new Blob([toCsv(list.rows)], { type: "text/csv;charset=utf-8;" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `cheques-${new Date().toISOString().slice(0, 10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}

	const pages = Math.ceil(list.total / PAGE_SIZE);

	return (
		<div className="mx-auto max-w-[1440px] px-4 py-6">
			<PageHeader
				title={__("Cheques")}
				description={__("Every cheque from the day it arrives to the day it clears.")}
			>
				<Button variant="secondary" onClick={exportCsv} disabled={!list.rows.length}>
					<Download size={14} />
					{__("Export")}
				</Button>
			</PageHeader>

			{error && (
				<Alert tone="danger" action={{ label: __("Retry"), onClick: refreshAll }}>
					{error}
				</Alert>
			)}
			{notice && <div className="mt-3">{<Alert tone={notice.tone}>{notice.text}</Alert>}</div>}

			<div className="mt-4">
				<ChequeFilters
					value={filters}
					onChange={applyFilters}
					onReset={() => applyFilters(DEFAULT_FILTERS)}
					busy={loading}
				/>
			</div>

			{checked.length > 0 && (
				<div className="mt-3 flex items-center gap-3 rounded-xl border border-accent bg-accent-soft px-3 py-2">
					<span className="text-sm text-accent-soft-fg">
						{__("{0} selected", [checked.length])}
					</span>
					<Button variant="primary" size="sm" onClick={() => setBulkOpen(true)}>
						<Landmark size={14} />
						{__("Deposit selected")}
					</Button>
					<Button variant="ghost" size="sm" onClick={() => setChecked([])}>
						{__("Clear selection")}
					</Button>
				</div>
			)}

			<div className="mt-4 grid gap-4 lg:grid-cols-5">
				<div className="lg:col-span-3">
					<Card padded={false}>
						<ChequeTable
							cheques={list.rows}
							loading={loading}
							selected={selected}
							onSelect={setSelected}
							checked={checked}
							onCheck={setChecked}
							sort={sort}
							onSort={onSort}
							precision={list.precision}
						/>

						{pages > 1 && (
							<div className="flex items-center justify-between border-t border-border px-3 py-2 text-sm">
								<span className="text-content-muted">
									{__("{0} of {1}", [list.rows.length, list.total])}
								</span>
								<div className="flex gap-1">
									<Button
										variant="ghost"
										size="sm"
										disabled={page === 0}
										onClick={() => setPage((p) => p - 1)}
									>
										{__("Previous")}
									</Button>
									<Button
										variant="ghost"
										size="sm"
										disabled={page + 1 >= pages}
										onClick={() => setPage((p) => p + 1)}
									>
										{__("Next")}
									</Button>
								</div>
							</div>
						)}
					</Card>
				</div>

				<div className="lg:col-span-2">
					{selected ? (
						<ChequeDetail detail={detail} loading={detailLoading} onChanged={refreshAll} />
					) : (
						<Card>
							<p className="text-sm text-content-muted">
								{__("Select a cheque to see where it is and what you can do with it.")}
							</p>
						</Card>
					)}
				</div>
			</div>

			<ConfirmDialog
				open={bulkOpen}
				danger={false}
				title={__("Deposit {0} cheques?", [checked.length])}
				message={__(
					"Each one is recorded as being with the bank for collection. Your bank balance does not change until they clear."
				)}
				confirmLabel={bulkBusy ? __("Working…") : __("Deposit")}
				cancelLabel={__("Cancel")}
				onConfirm={() => !bulkBusy && runBulkDeposit()}
				onCancel={() => !bulkBusy && setBulkOpen(false)}
			/>
		</div>
	);
}
