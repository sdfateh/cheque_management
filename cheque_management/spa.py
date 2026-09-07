from sanawbar import spa as shared_spa

script_safe_json = shared_spa.script_safe_json

TRANSLATION_APPS = ("sanawbar", "cheque_management")


def build_config(**flags):
	config = shared_spa.build_config(
		app_name="cheque_management",
		translation_apps=TRANSLATION_APPS,
		csrf_refresh_path="/cheques",
		**flags,
	)
	config["sentry"] = shared_spa.sentry_config(
		product="cheques",
		dsn_env="CHEQUES_SENTRY_DSN",
		release_env="CHEQUES_SENTRY_RELEASE",
	)
	return config


__all__ = ("build_config", "script_safe_json")
