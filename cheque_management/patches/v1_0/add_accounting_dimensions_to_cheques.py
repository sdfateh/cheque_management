"""Add already-configured ERPNext accounting dimensions to MFG Cheque."""

from cheque_management.cheque_fields import create_cheque_accounting_dimension_fields


def execute():
	create_cheque_accounting_dimension_fields()
