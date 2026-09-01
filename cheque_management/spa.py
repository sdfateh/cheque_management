from sanawbar.spa import build_config as _build_config
from sanawbar.spa import script_safe_json

TRANSLATION_APPS = ("sanawbar", "cheque_management")


def build_config(**flags):
	return _build_config(
		app_name="cheque_management",
		translation_apps=TRANSLATION_APPS,
		csrf_refresh_path="/cheques",
		**flags,
	)


__all__ = ("build_config", "script_safe_json")
