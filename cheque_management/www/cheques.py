# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Serve the permission-gated /cheques SPA.

Cheque management is its own product with its own audience: the people who
deposit and chase cheques are accounts staff, and they have no business in a cost
estimator. It is an independent app that consumes the shared Sanawbar.

So: separate page, separate permission gate, no link between the two, and neither
one's permissions open the other. An accounts user who cannot touch a Job Card
gets this page; a shop-floor operator does not.

What the two pages share is presentation infrastructure, not bundles or policy.
"""

import frappe

from cheque_management.i18n import _
from cheque_management.spa import build_config, script_safe_json

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to manage cheques."), frappe.PermissionError)

	# Read on the cheque record is the entry ticket; write decides whether the
	# lifecycle buttons render. Every endpoint re-checks for itself, so this gate
	# only avoids showing someone a screen that would reject them.
	can_read = bool(frappe.has_permission("MFG Cheque", "read"))
	if not can_read:
		frappe.throw(
			_("You do not have permission to manage cheques."),
			frappe.PermissionError,
		)

	config = build_config(
		can_manage_cheques=can_read,
		can_write_cheques=bool(frappe.has_permission("MFG Cheque", "write")),
	)

	context.update(
		{
			"build_version": frappe.utils.get_build_version(),
			"app_config": script_safe_json(config),
		}
	)

	return context
