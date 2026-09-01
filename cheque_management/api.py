import json

import frappe

from cheque_management.i18n import _

SEARCHABLE_DOCTYPES = {"Customer", "Supplier"}
MAX_SEARCH_LIMIT = 50


@frappe.whitelist()
def search_link(doctype, txt=None, filters=None, limit=15):
	from frappe.desk.search import search_link as frappe_search_link

	if not frappe.has_permission("MFG Cheque", "read"):
		frappe.throw(_("You do not have permission to manage cheques."), frappe.PermissionError)
	if doctype not in SEARCHABLE_DOCTYPES:
		frappe.throw(_("Link search is not available for {0}.").format(doctype), frappe.PermissionError)
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except (TypeError, ValueError):
			frappe.throw(_("Search filters must be an object or list."))
	filters = filters or {}
	if not isinstance(filters, (dict, list)):
		frappe.throw(_("Search filters must be an object or list."))
	try:
		page_length = max(1, min(int(limit or 15), MAX_SEARCH_LIMIT))
	except (TypeError, ValueError):
		page_length = 15
	results = frappe_search_link(
		doctype=doctype,
		txt=(txt or "").strip(),
		filters=filters,
		page_length=page_length,
	)
	return _add_titles(doctype, results)


def _add_titles(doctype, results):
	meta = frappe.get_meta(doctype)
	title_field = meta.get_title_field()
	if not title_field or title_field == "name" or meta.show_title_field_in_link:
		return results
	names = [row["value"] for row in results if row.get("value")]
	if not names:
		return results
	titles = dict(
		frappe.get_list(
			doctype,
			filters={"name": ("in", names)},
			fields=["name", title_field],
			as_list=True,
			limit_page_length=MAX_SEARCH_LIMIT,
		)
	)
	for row in results:
		title = titles.get(row.get("value"))
		if title and title != row["value"]:
			row["label"] = title
	return results
