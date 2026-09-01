from cheque_management.reporting import execute_report


def execute(filters=None):
	return execute_report("Cheques by Bank", filters)
