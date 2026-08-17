# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The billing date — the day of the month a team is charged.

Some teams simply do not have the money in the account on the 1st. Their card
declines on the 1st, declines again on the 3rd, and then goes through untouched
on the 5th or the 9th: nothing was ever wrong with the card, the balance just
wasn't there yet. Every one of those declines costs the customer a failed-payment
notice and costs us a rung of the dunning ladder, for a bill that was always going
to be paid. A team that knows which day it is funded should be able to say so, the
way a bank lets you pick your EMI date.

So a team may name its billing date, and it moves exactly one thing: the earliest
date the *automatic* charge may run. Everything else holds still. The period is
still the calendar month, the invoice is still issued on the 1st for the month
that just closed, credits are still applied the moment it opens, and the customer
can still pay it themselves the day they see it.

The due date and the dunning ladder do not move with it either, deliberately: the
window to settle is the same whichever day a team picked, so a later billing date
buys a better first attempt rather than a longer float. That is only safe while the
chosen day lands before the invoice falls due, which is what Billing Settings
enforces on `max_billing_date`.

Two switches guard it, because the effect is money arriving later than it does
today: `allow_custom_billing_date` on Billing Settings turns the feature on at all,
and the same flag on the team's Billing Profile grants it to that team. Both must
be on for a day to be honoured, so revoking either puts the team back on "charge as
soon as the invoice opens" without anyone having to unset the day itself.
"""

import calendar

import frappe
from frappe import _

from central.billing import settings

# Only an automatic off-session debit can be scheduled. Manual Checkout means the
# customer pays on-session whenever they choose, and Prepaid draws a wallet that was
# funded in advance — neither has a debit date for the customer to move.
SCHEDULABLE_MODES = ("Auto Charge",)


def feature_enabled() -> bool:
	"""Whether custom billing dates are switched on for the site at all."""
	return settings.allow_custom_billing_date()


def available(team: str) -> bool:
	"""Whether this team may name its billing date: the site allows it and the team
	has been granted it."""
	return feature_enabled() and bool(
		frappe.db.get_value("Billing Profile", team, "allow_custom_billing_date")
	)


def billing_date(team: str) -> int:
	"""The day of the month this team is charged on, or 0 for "when the invoice opens".

	Clamped to the configured window rather than trusted: a day saved while the
	window was wider must not keep collecting late after the window is narrowed.
	"""
	if not available(team):
		return 0
	day = frappe.utils.cint(frappe.db.get_value("Billing Profile", team, "billing_date"))
	if day <= 1:
		return 0
	return min(day, max(settings.max_billing_date(), 1))


def _day_in_month(day: int, month_of):
	"""`day` as a date in `month_of`'s month, never past the end of a short one."""
	on = frappe.utils.getdate(month_of)
	return on.replace(day=min(day, calendar.monthrange(on.year, on.month)[1]))


def scheduled_charge_date(team: str, opened_on=None):
	"""The date an invoice opening today must wait for, or None to charge it now.

	None for almost every team — the answer is a date only for a team that named a
	later day and is on a mode we debit off-session at all. Returning None rather
	than "today" is what keeps the stamp on the invoice meaningful: `collect_on` is
	set precisely on the invoices whose charge is being held, so the sweep that
	makes the late ask can find them by that field alone.

	A day that has already passed is not honoured: an invoice the run opens on the
	9th for a team billed on the 5th is charged now, not held for three weeks. The
	setting exists to stop us asking too early, never to stop us asking at all.
	"""
	opened_on = frappe.utils.getdate(opened_on or frappe.utils.nowdate())
	day = billing_date(team)
	if not day:
		return None
	if frappe.db.get_value("Billing Profile", team, "collection_mode") not in SCHEDULABLE_MODES:
		return None
	scheduled = _day_in_month(day, opened_on)
	return scheduled if scheduled > opened_on else None


def is_deferred(collect_on_date, on=None) -> bool:
	"""Whether an invoice's automatic charge is still waiting for its billing date."""
	if not collect_on_date:
		return False
	return frappe.utils.getdate(collect_on_date) > frappe.utils.getdate(on)


def announce(invoice) -> None:
	"""Tell the customer the bill is issued and when it will be taken.

	A team on a custom billing date gets an invoice that visibly is not being paid
	yet. Silence there reads as a system that has forgotten to charge them, so the
	date they chose is said back to them once, when the invoice opens."""
	from central.billing.platform import notifications

	notifications.notify(
		invoice.team,
		"Payment Scheduled",
		context={
			"amount": f"{frappe.utils.flt(invoice.expected_collection)} {invoice.currency or ''}".strip(),
			"charge_on": frappe.utils.format_date(invoice.collect_on),
		},
		message=_("We'll take this payment on {0}, the date you picked.").format(
			frappe.utils.format_date(invoice.collect_on)
		),
		reference_doctype="Invoice",
		reference_name=invoice.name,
	)


def validate_day(day: int, team: str | None = None) -> int:
	"""Check a day against the configured window; returns it as an int."""
	day = frappe.utils.cint(day)
	limit = settings.max_billing_date()
	if day and not (1 <= day <= limit):
		frappe.throw(
			_("Pick a billing date between 1 and {0}.").format(limit),
			frappe.ValidationError,
		)
	if day and team and not available(team):
		frappe.throw(
			_("This team is not set up to choose its own billing date."),
			frappe.ValidationError,
		)
	return day


def choose(team: str, day) -> dict:
	"""The customer picks the day of the month they are charged.

	Takes effect from the next invoice: an invoice already open carries the date it
	was stamped with, so a change never moves a charge the customer has already been
	told about.
	"""
	day = validate_day(day, team)
	profile = frappe.get_doc("Billing Profile", team)
	profile.billing_date = day
	profile.save(ignore_permissions=True)
	return status(team)


def status(team: str) -> dict:
	"""What the billing-date control on the settings screen renders from."""
	limit = max(settings.max_billing_date(), 1)
	return {
		"available": available(team),
		"day": billing_date(team),
		"max_day": limit,
		"choices": list(range(1, limit + 1)),
	}
