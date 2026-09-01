# Copyright (c) 2026, Salah and contributors
# For license information, please see license.txt
"""Add the cheque custom fields and the Cheque Manager role.

Mirrors `after_install` for sites that already have the app installed.
"""

from cheque_management.cheque_fields import create_cheque_fields


def execute():
	create_cheque_fields()
