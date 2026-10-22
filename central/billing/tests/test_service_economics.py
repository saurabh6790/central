# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe

from central.billing.platform import invariants, readiness
from central.billing.report import _services
from central.billing.report.service_profitability import service_profitability
from central.billing.tests.utils import BillingTestCase, billing_settings, ensure_team, make_metered_plan
from central.integrations.grove import GroveClient, GroveUnavailable
from central.services.doctype.team_service.team_service import AI_SERVICE

MONTH = "2026-09-01"
TRANSFER = "Transfer"


def overage_line(team: str, quantity: float, amount: float, resource_type: str = TRANSFER):
	"""An overage line as BilledMonth reads it: no plan, its family's service, revenue in INR."""
	return frappe._dict(
		team=team,
		service="Metered Resources",
		resource_type=resource_type,
		plan=None,
		quantity=quantity,
		unit="GB",
		revenue_inr=amount,
		cost_inr=0.0,
		days=0,
		hours=0,
		vcpus=0,
	)


def record_usage(team: str, quantity: float, allowance: float = 0, rate: float = 0.5):
	ensure_team(team)
	frappe.get_doc(
		{
			"doctype": "Usage Rollup",
			"resource_id": f"subject-{team}",
			"team": team,
			"resource_type": TRANSFER,
			"meter_type": "Counter",
			"period_start": f"{MONTH} 00:00:00",
			"period_end": "2026-09-30 00:00:00",
			"quantity": quantity,
			"unit": "GB",
			"currency": "INR",
			"locked_allowance": allowance,
			"locked_rate": rate,
			"idempotency_key": f"test-service-economics-{team}",
		}
	).insert(ignore_permissions=True)


def enable_ai(team: str):
	ensure_team(team)
	# Skip Team Service's insert hooks: they register the team at Grove.
	frappe.get_doc(
		{"doctype": "Team Service", "team": team, "add_on_service": AI_SERVICE, "status": "Active"}
	).db_insert()


def grove_reports(usage: dict | None = None, error: Exception | None = None):
	client = MagicMock()
	client.get_usage.side_effect = error
	client.get_usage.return_value = usage
	return patch.object(GroveClient, "from_settings", return_value=client)


def rows_for(lines: list, filters: dict | None = None) -> dict:
	with patch("central.billing.report._economics.BilledMonth._load", return_value=lines):
		_, rows, message, *_ = service_profitability.execute({"month": MONTH, **(filters or {})})
	return {row["service"]: row for row in rows}, message


class TestServiceEconomics(BillingTestCase):
	def setUp(self):
		make_metered_plan("svc-test-transfer", TRANSFER, quantity=100)
		frappe.db.set_value("Resource Type", TRANSFER, "cost_per_unit_inr", 0.4)
		frappe.db.delete("Usage Rollup", {"period_start": ["between", [MONTH, "2026-09-30"]]})
		frappe.db.delete("Team Service", {"add_on_service": AI_SERVICE})

	def test_cost_follows_used_units_not_billed_units(self):
		# 1,000 GB used, 100 GB free, 900 GB billed at 0.5: revenue 450, cost 400.
		record_usage("team-se-a", 1000, allowance=100)
		rows, _ = rows_for([overage_line("team-se-a", 900, 450)])
		row = rows["Metered Resources"]

		self.assertEqual((row["used"], row["billed"]), (1000, 900))
		self.assertAlmostEqual(row["cost"], 400)
		self.assertAlmostEqual(row["free_units_cost"], 40)
		self.assertEqual(row["verdict"], _services.THIN)

	def test_a_service_that_costs_more_than_it_earns_is_a_loss(self):
		frappe.db.set_value("Resource Type", TRANSFER, "cost_per_unit_inr", 0.6)
		record_usage("team-se-a", 1000)
		rows, _ = rows_for([overage_line("team-se-a", 1000, 500)])

		self.assertEqual(rows["Metered Resources"]["verdict"], _services.LOSS)

	def test_usage_with_no_provider_cost_is_flagged_not_counted_as_margin(self):
		frappe.db.set_value("Resource Type", TRANSFER, "cost_per_unit_inr", 0)
		record_usage("team-se-a", 1000)
		rows, _ = rows_for([overage_line("team-se-a", 1000, 500)])

		self.assertEqual(rows["Metered Resources"]["verdict"], _services.COST_NOT_SET)

	def test_usage_no_invoice_carries_is_not_billed(self):
		record_usage("team-se-a", 1000)
		rows, _ = rows_for([])
		row = rows["Metered Resources"]

		self.assertEqual((row["value"], row["revenue"], row["not_billed"]), (500, 0, 500))
		self.assertEqual(row["verdict"], _services.NOT_BILLED)

	def test_our_own_teams_usage_costs_us_but_is_not_a_billing_gap(self):
		frappe.get_doc(
			{
				"doctype": "Tax Profile",
				"team": ensure_team("team-se-ours"),
				"is_internal": 1,
				"internal_reason": "Ours",
			}
		).insert(ignore_permissions=True)
		record_usage("team-se-ours", 1000)
		rows, _ = rows_for([])
		row = rows["Metered Resources"]

		self.assertEqual((row["not_billed"], row["cost"]), (None, 400))
		self.assertEqual(row["verdict"], _services.LOSS)

	def test_ai_spend_at_grove_with_no_invoice_line_is_not_billed(self):
		frappe.db.set_value("Resource Type", _services.AI_RESOURCE_TYPE, "cost_per_unit_inr", 0.1)
		enable_ai("team-se-ai")
		usage = {"team-se-ai": {"requests": 10, "tokens": 1000, "cost": 10.0}}
		with (
			billing_settings(reporting_usd_to_inr=85),
			grove_reports(usage) as from_settings,
			self.freeze_time("2026-10-15"),
		):
			rows, _ = rows_for([])
			flags = readiness.check_services_pay_for_themselves()

		row = rows[_services.AI_RESOURCE_TYPE]
		self.assertEqual((row["used"], row["value"]), (1000, 850))
		self.assertEqual(row["verdict"], _services.NOT_BILLED)
		self.assertIn(_services.AI_RESOURCE_TYPE, {flag.subject for flag in flags})
		from_settings.return_value.get_usage.assert_called_with(["team-se-ai"], month="2026-09")

	def test_the_report_opens_while_grove_is_down_and_says_ai_is_missing(self):
		enable_ai("team-se-ai")
		with grove_reports(error=GroveUnavailable()):
			rows, message = rows_for([])

		self.assertNotIn(_services.AI_RESOURCE_TYPE, rows)
		self.assertIn("Grove could not be read", message)

	def test_the_audit_stores_the_red_flag_count_for_the_dashboards(self):
		record_usage("team-se-a", 1000)
		with self.freeze_time("2026-10-15"):
			flags = readiness.check_services_pay_for_themselves()
		with patch.object(invariants, "audit", side_effect=[[], flags]):
			result = invariants.run_invariant_audit()

		self.assertEqual(
			frappe.db.get_single_value("Billing Settings", "open_red_flags"), result["violations"]
		)
		self.assertGreater(result["violations"], 0)
