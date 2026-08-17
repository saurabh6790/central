# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Give an existing Billing Settings the shipped billing-date window.

A field default only reaches documents created after it exists, and Billing
Settings is a Single that every site saved long ago. So the new `max_billing_date`
reads 0 on every upgraded site, and the first admin to switch custom billing dates
on meets a validation error instead of the sensible 7 the DocType advertises.

Only where nothing is configured, and never re-asserted on later migrates: the
window is the business's to narrow.
"""

import frappe

SHIPPED_WINDOW = 7


def execute():
	if frappe.db.get_single_value("Billing Settings", "max_billing_date"):
		return
	due_days = frappe.utils.cint(frappe.db.get_single_value("Billing Settings", "invoice_due_days"))
	# Never past the due date — the same rule the Single validates (billing_date.py).
	window = min(SHIPPED_WINDOW, due_days) if due_days else SHIPPED_WINDOW
	frappe.db.set_single_value("Billing Settings", "max_billing_date", max(window, 1))
