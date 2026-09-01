// One place deciding what a cheque status looks like, so the list, the detail
// header and the action modals never disagree about it.
//
// Tones are the Badge tones already used elsewhere in the app.

export const STATUS_TONE = {
	"Post-Dated Held": "neutral",
	Received: "info",
	Issued: "info",
	Deposited: "warning",
	Cleared: "success",
	Bounced: "danger",
	"Returned to Customer": "danger",
	Replaced: "neutral",
	Cancelled: "neutral",
};

// Labels for the lifecycle actions. Keyed by the action names the server
// exposes, so a new transition surfaces here rather than silently rendering a
// raw identifier.
export const ACTION_LABEL = {
	mature: "Mature",
	deposit: "Deposit",
	clear: "Clear",
	bounce: "Bounce",
	return_to_party: "Return to Customer",
	replace: "Replace",
};

// Which actions are destructive enough to warrant the danger styling.
export const DESTRUCTIVE_ACTIONS = new Set(["bounce"]);

export function statusTone(status) {
	return STATUS_TONE[status] || "neutral";
}

// Statuses where the cheque is still live money we are waiting on.
export const OUTSTANDING = new Set(["Post-Dated Held", "Received", "Issued", "Deposited"]);
