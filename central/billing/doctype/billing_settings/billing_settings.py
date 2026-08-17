# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing policy knobs, in one place.

These are the numbers the business changes without shipping code: what a new team
is granted, how long that grant lives, when an unpaid invoice is chased. They were
constants scattered across the billing modules; they are one Single now.

Read them through `central.billing.settings`, never off this document directly —
that module carries the fallback for a knob nobody has configured yet.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# The window an admin gets by switching custom billing dates on without naming one.
DEFAULT_BILLING_DATE_WINDOW = 7


class BillingSettings(Document):
	def validate(self):
		self.validate_retry_days()
		self.validate_dunning_ladder()
		self.validate_billing_date_window()
		self.validate_one_row_per_currency()

	def retry_days(self) -> list[int]:
		"""The dunning retry days, parsed, de-duplicated and in order.

		Returns an empty list for a blank or unparseable value; `validate` is what
		refuses to store junk, so readers never have to."""
		days = []
		for part in (self.dunning_retry_days or "").split(","):
			part = part.strip()
			if not part:
				continue
			try:
				days.append(int(part))
			except ValueError:
				return []
		return sorted(set(days))

	def validate_retry_days(self):
		"""Every retry day must be a positive whole number of days past due."""
		raw = [p.strip() for p in (self.dunning_retry_days or "").split(",") if p.strip()]
		days = self.retry_days()
		if len(days) != len(raw) or any(day < 1 for day in days):
			frappe.throw(
				_("Retry Days must be positive whole numbers, comma separated — for example 1, 3, 7."),
				title=_("Invalid Retry Days"),
			)
		self.dunning_retry_days = ", ".join(str(day) for day in days)

	def validate_dunning_ladder(self):
		"""Suspension follows the last retry, and termination follows suspension.

		A ladder out of order would suspend a team the collection run was still
		retrying, or terminate one before it was ever suspended."""
		days = self.retry_days()
		if days and self.suspend_after_days and self.suspend_after_days <= days[-1]:
			frappe.throw(
				_("Suspend After must be later than the last retry day ({0}).").format(days[-1]),
				title=_("Invalid Dunning Ladder"),
			)
		if self.terminate_after_days and self.terminate_after_days <= (self.suspend_after_days or 0):
			frappe.throw(
				_("Terminate After must be later than Suspend After."),
				title=_("Invalid Dunning Ladder"),
			)

	def validate_billing_date_window(self):
		"""The latest billing date must still fall before the invoice is due.

		The chosen day moves the charge, not the deadline: due date, retries and
		suspension stay pinned to the day the invoice opened. A window that reached
		past the due date would therefore let us declare a customer overdue for money
		we had not asked for yet, which is the opposite of what the setting is for.
		"""
		if not self.allow_custom_billing_date:
			return
		# Switching the feature on without naming a window is not a mistake to
		# correct the admin about — it means "the usual". Fill it in rather than
		# refusing the save, since the field reads 0 on every site that saved this
		# Single before the field existed (see the seed_max_billing_date patch).
		if not frappe.utils.cint(self.max_billing_date):
			self.max_billing_date = min(DEFAULT_BILLING_DATE_WINDOW, frappe.utils.cint(self.invoice_due_days))
		if not 1 <= frappe.utils.cint(self.max_billing_date) <= 28:
			frappe.throw(
				_("Latest Billing Date must be a day between 1 and 28."),
				title=_("Invalid Billing Date Window"),
			)
		if frappe.utils.cint(self.max_billing_date) > frappe.utils.cint(self.invoice_due_days):
			frappe.throw(
				_("Latest Billing Date must be on or before the day an invoice falls due ({0}).").format(
					self.invoice_due_days
				),
				title=_("Invalid Billing Date Window"),
			)

	def validate_one_row_per_currency(self):
		"""One grant amount per currency — two rows would make the grant ambiguous."""
		seen = set()
		for row in self.welcome_credit_amounts:
			if row.currency in seen:
				frappe.throw(
					_("Row {0}: {1} already has a welcome credit amount.").format(row.idx, row.currency),
					title=_("Duplicate Currency"),
				)
			seen.add(row.currency)
