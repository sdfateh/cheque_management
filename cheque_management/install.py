from cheque_management.cheque_fields import (
	create_cheque_accounting_dimension_fields,
	create_cheque_fields,
	create_cheque_role,
)


def before_install():
	# DocType permissions reference Cheque Manager during model sync, so the role
	# must exist before Frappe imports the DocType JSON files.
	create_cheque_role()


def after_install():
	create_cheque_fields()
	# Patches are marked completed on a fresh app install, so the upgrade patch
	# cannot supply dimensions that ERPNext already had before this app existed.
	create_cheque_accounting_dimension_fields()
