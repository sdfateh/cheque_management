app_name = "cheque_management"
app_title = "Cheque Management"
app_publisher = "Salah"
app_description = "Cheque lifecycle management for ERPNext"
app_email = "salahaldinfateh@gmail.com"
app_license = "mit"

app_include_js = ["/assets/cheque_management/js/cheque_reports.js"]

required_apps = ["erpnext", "sanawbar"]

add_to_apps_screen = [
	{
		"name": "cheque_management",
		"logo": "/assets/sanawbar/images/sanawbar.png",
		"title": "Cheques",
		"route": "/cheques",
	}
]

website_route_rules = [
	{"from_route": "/cheques/<path:app_path>", "to_route": "cheques"},
]

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Mode of Payment-custom_mfg_is_cheque",
					"Payment Entry-custom_mfg_cheque_section",
					"Payment Entry-custom_mfg_cheque_type",
					"Payment Entry-custom_mfg_drawee_bank",
					"Payment Entry-custom_mfg_cheque_col_break",
					"Payment Entry-custom_mfg_bank_account",
					"Payment Entry-custom_mfg_replaces",
					"Payment Entry-custom_mfg_cancellation_reason",
					"Payment Entry-custom_mfg_cheque",
					"Journal Entry-custom_mfg_cheque",
				],
			]
		],
	}
]

doctype_js = {
	"Payment Entry": "public/js/payment_entry.js",
}

before_install = "cheque_management.install.before_install"
after_install = "cheque_management.install.after_install"

doc_events = {
	"Payment Entry": {
		"validate": "cheque_management.cheque_events.validate",
		"before_submit": "cheque_management.cheque_events.before_submit",
		"on_submit": "cheque_management.cheque_events.on_submit",
		"on_cancel": "cheque_management.cheque_events.on_cancel",
	},
}

scheduler_events = {
	"daily": [
		"cheque_management.cheque_operations.mature_post_dated_cheques",
	],
}
