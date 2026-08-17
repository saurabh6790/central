# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The team's chosen billing date — we ask on their day, not on the 1st."""

from contextlib import contextmanager
from unittest.mock import patch

import frappe

from central.billing.payments import billing_date, collection, emandate
from central.billing.revenue import dunning
from central.billing.revenue.invoicing import lifecycle
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	billing_settings,
	clear_team_tier,
	complete_billing_profile,
	ensure_team,
)

TEAM = "team-billing-date"


@contextmanager
def on_date(today):
	"""Run as if today were `today`. The whole feature is date arithmetic, and the
	only interesting dates are the first week of a month."""
	with patch("frappe.utils.nowdate", return_value=today):
		yield


def _profile(**values):
	doc = frappe.get_doc("Billing Profile", TEAM)
	doc.update(values)
	doc.save(ignore_permissions=True)
	return doc


class BillingDateTestCase(IntegrationTestCase):
	"""A team billed on the 5th, on a site where custom billing dates are on."""

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		clear_team_tier(TEAM)
		for doctype in ("Payment Attempt", "Invoice", "Billing Notification Log"):
			frappe.db.delete(doctype, {"team": TEAM})
		self.settings = billing_settings(allow_custom_billing_date=1, max_billing_date=7)
		self.settings.__enter__()
		_profile(collection_mode="Auto Charge", allow_custom_billing_date=1, billing_date=5)

	def tearDown(self):
		self.settings.__exit__(None, None, None)

	def _draft(self, amount=5000, period=("2026-05-01", "2026-05-31")):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Draft",
					"period_start": period[0],
					"period_end": period[1],
					"currency": "INR",
					"subtotal": amount,
					"total": amount,
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": amount, "days": 30, "amount": amount}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestBillingDateResolution(BillingDateTestCase):
	def test_the_chosen_day_is_what_an_invoice_waits_for(self):
		self.assertEqual(
			str(billing_date.scheduled_charge_date(TEAM, "2026-06-01")), "2026-06-05"
		)

	def test_a_day_that_has_passed_is_charged_now(self):
		"""An invoice the run opens late is asked for today, not held for a month."""
		self.assertIsNone(billing_date.scheduled_charge_date(TEAM, "2026-06-09"))

	def test_nothing_waits_without_the_site_switch(self):
		with billing_settings(allow_custom_billing_date=0):
			self.assertIsNone(billing_date.scheduled_charge_date(TEAM, "2026-06-01"))

	def test_nothing_waits_without_the_team_grant(self):
		_profile(allow_custom_billing_date=0)
		self.assertIsNone(billing_date.scheduled_charge_date(TEAM, "2026-06-01"))

	def test_a_day_beyond_the_window_is_clamped(self):
		frappe.db.set_value("Billing Profile", TEAM, "billing_date", 20)
		self.assertEqual(billing_date.billing_date(TEAM), 7)

	def test_only_an_automatic_mode_has_a_date_to_move(self):
		"""Manual Checkout pays on-session and Prepaid draws a funded wallet —
		neither has an off-session debit for the customer to schedule."""
		for mode in ("Manual Checkout", "Prepaid", "Action Required"):
			_profile(collection_mode=mode)
			self.assertIsNone(billing_date.scheduled_charge_date(TEAM, "2026-06-01"), mode)


class TestDeferredCollection(BillingDateTestCase):
	def test_opening_stamps_the_date_and_does_not_ask(self):
		invoice = self._draft()
		with on_date("2026-06-01"), patch.object(collection, "collect_invoice") as charge:
			out = lifecycle.open_and_collect(invoice)
		charge.assert_not_called()

		doc = frappe.get_doc("Invoice", invoice)
		self.assertEqual(doc.status, "Open")
		self.assertTrue(out["scheduled"])
		self.assertEqual(str(doc.collect_on), "2026-06-05")

	def test_the_customer_is_told_when_the_money_goes(self):
		with on_date("2026-06-01"), patch.object(collection, "collect_invoice"):
			lifecycle.open_and_collect(self._draft())
		self.assertTrue(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Payment Scheduled"}
			)
		)

	def test_the_due_date_and_the_ladder_stay_where_they_were(self):
		"""The billing date moves when we ask, never how long they have to pay."""
		invoice = self._draft()
		with on_date("2026-06-01"), patch.object(collection, "collect_invoice"):
			lifecycle.open_and_collect(invoice)
		doc = frappe.get_doc("Invoice", invoice)
		# Opened on the 1st, so due on the 8th — the billing date does not touch it.
		self.assertEqual(str(doc.due_date), "2026-06-08")
		self.assertEqual(str(doc.dunning_starts_on), "2026-06-08")

	def test_a_team_without_the_grant_is_charged_on_open_as_before(self):
		_profile(allow_custom_billing_date=0)
		invoice = self._draft()
		with on_date("2026-06-01"), patch.object(collection, "collect_invoice") as charge:
			lifecycle.open_and_collect(invoice)
		charge.assert_called_once_with(invoice)
		self.assertIsNone(frappe.db.get_value("Invoice", invoice, "collect_on"))


class TestScheduledSweep(BillingDateTestCase):
	def _held(self, collect_on):
		invoice = self._draft()
		doc = frappe.get_doc("Invoice", invoice)
		doc.status = "Open"
		doc.expected_collection = doc.total
		doc.due_date = "2026-06-08"
		doc.collect_on = collect_on
		doc.save(ignore_permissions=True)
		return invoice

	def test_nothing_is_asked_before_the_day(self):
		self._held("2026-06-05")
		with patch.object(collection, "collect_invoice") as charge:
			collection.charge_scheduled_invoices(today="2026-06-04")
		charge.assert_not_called()

	def test_the_day_arrives_and_we_ask(self):
		invoice = self._held("2026-06-05")
		with patch.object(collection, "collect_invoice", return_value={"collected": True}) as charge:
			out = collection.charge_scheduled_invoices(today="2026-06-05")
		charge.assert_called_once_with(invoice)
		self.assertEqual(out[0]["invoice"], invoice)

	def test_an_invoice_already_asked_belongs_to_the_ladder(self):
		"""Once a charge has been attempted, dunning owns the retries — a daily
		sweep charging alongside it would try the same card twice in a day."""
		invoice = self._held("2026-06-05")
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": invoice,
				"team": TEAM,
				"amount": 5000,
				"status": "Failed",
			}
		).insert(ignore_permissions=True)
		with patch.object(collection, "collect_invoice") as charge:
			collection.charge_scheduled_invoices(today="2026-06-06")
		charge.assert_not_called()

	def test_a_notice_rail_is_left_to_the_emandate_cycle(self):
		self._held("2026-06-05")
		with (
			patch.object(emandate, "rail_requires_notice", return_value=True),
			patch.object(collection, "collect_invoice") as charge,
		):
			collection.charge_scheduled_invoices(today="2026-06-05")
		charge.assert_not_called()


class TestDunningWaitsForTheDate(BillingDateTestCase):
	def test_no_retry_before_the_day_we_promised(self):
		invoice = self._draft()
		doc = frappe.get_doc("Invoice", invoice)
		doc.status = "Open"
		doc.expected_collection = doc.total
		doc.due_date = "2026-06-01"
		doc.dunning_starts_on = "2026-06-01"
		doc.collect_on = "2026-06-05"
		doc.save(ignore_permissions=True)

		with patch.object(dunning, "retry_payment") as retry:
			dunning.process_invoice_dunning(invoice, now="2026-06-03")
		retry.assert_not_called()


class TestEmandateHonoursTheDate(BillingDateTestCase):
	"""On a rail that owes a pre-debit notice, the notice is the ask — so it is
	armed a day before the billing date, not the day the invoice opens."""

	def setUp(self):
		super().setUp()
		self.invoice = self._draft()
		doc = frappe.get_doc("Invoice", self.invoice)
		doc.status = "Open"
		doc.expected_collection = doc.total
		doc.collect_on = "2026-06-05"
		doc.save(ignore_permissions=True)

	def test_the_notice_waits_until_the_day_before(self):
		with (
			patch.object(emandate, "rail_requires_notice", return_value=True),
			patch.object(emandate.collection_mode, "evaluate", return_value={"action_required": False}),
		):
			out = emandate.schedule_predebit(self.invoice, now="2026-06-02 09:00:00")
		self.assertEqual(out["skipped"], "awaiting_billing_date")

	def test_the_debit_window_closes_on_the_day(self):
		with (
			patch.object(emandate, "rail_requires_notice", return_value=True),
			patch.object(emandate.collection_mode, "evaluate", return_value={"action_required": False}),
		):
			emandate.schedule_predebit(self.invoice, now="2026-06-04 09:00:00")
		charge_after = frappe.db.get_value("Invoice", self.invoice, "predebit_charge_after")
		self.assertEqual(str(charge_after), "2026-06-05 09:00:00")


class TestBillingDateValidation(BillingDateTestCase):
	def test_a_day_outside_the_window_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(billing_date=9)

	def test_a_day_needs_the_site_switch(self):
		with billing_settings(allow_custom_billing_date=0), self.assertRaises(frappe.ValidationError):
			_profile(billing_date=3)

	def test_revoking_the_grant_clears_the_day(self):
		"""Ops takes the grant away; the team goes back to being charged on open,
		and the profile stays editable."""
		_profile(allow_custom_billing_date=0)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "billing_date"), 0)

	def test_a_revoked_grant_leaves_the_profile_editable(self):
		"""The day is ignored once the grant is gone, but the profile still saves —
		an ops user must never be locked out of a team by an old setting."""
		with billing_settings(allow_custom_billing_date=0):
			_profile(legal_name="Renamed Ltd")
			self.assertIsNone(billing_date.scheduled_charge_date(TEAM, "2026-06-01"))

	def test_the_window_may_not_reach_past_the_due_date(self):
		with self.assertRaises(frappe.ValidationError):
			with billing_settings(allow_custom_billing_date=1, max_billing_date=20, invoice_due_days=7):
				pass

	def test_the_customer_picks_a_day(self):
		self.assertEqual(billing_date.choose(TEAM, 3)["day"], 3)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "billing_date"), 3)

	def test_the_customer_cannot_pick_past_the_window(self):
		with self.assertRaises(frappe.ValidationError):
			billing_date.choose(TEAM, 11)
