import frappe
from frappe import _ as frappe_translate
from sanawbar.spa import get_translations

TRANSLATION_APPS = ("sanawbar", "cheque_management")


def _(msg: str, lang: str | None = None, context: str | None = None) -> str:
	effective_lang = lang or getattr(frappe.local, "lang", None) or "en"
	catalogue = get_translations(effective_lang, TRANSLATION_APPS)
	key = frappe.as_unicode(msg).strip()
	if context and (translated := catalogue.get(f"{key}:{context}")):
		return translated
	if translated := catalogue.get(key):
		return translated
	return frappe_translate(msg, lang=lang, context=context)
