# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._economics import VM_SERVICE, BilledMonth, to_inr
from central.integrations.grove import GroveClient, GroveUnavailable
from central.services.doctype.team_service.team_service import AI_SERVICE

# Grove meters AI in tokens and reports what each team spent, in USD, at our price.
AI_RESOURCE_TYPE = "Tokens"

# Below this gross margin a service still earns, but a provider price rise would sink it.
THIN_MARGIN_PERCENT = 20

# Invoice lines round to the paisa, so a small gap between usage value and revenue is not a leak.
UNBILLED_TOLERANCE = 0.01

COST_NOT_SET = "Cost Not Set"
NOT_BILLED = "Not Billed"
LOSS = "Loss"
THIN = "Thin Margin"
PROFITABLE = "Profitable"


class ServiceMonth:
	"""Each service in one billed month: what was used, what was billed, what it cost us, and a verdict.

	Cost follows measured usage, not billed usage. Units inside an allowance, a prepaid pack, our
	own teams and usage that no invoice carries cost the provider the same as billed units."""

	def __init__(self, filters: dict | None = None):
		self.filters = filters or {}
		self.month = BilledMonth(self.filters)
		self.internal = set(frappe.get_all("Tax Profile", filters={"is_internal": 1}, pluck="team"))
		self.ai_unread = False
		self.usage = self._load_rollups() + self._load_ai_usage()

	def rows(self, by_team: bool = False) -> list[dict]:
		groups: dict = {}
		for line in self.month.lines:
			if self._wanted(line.service):
				_add_line(self._group(groups, line.service, line.team, by_team), line)
		for reading in self.usage:
			if self._wanted(reading.service):
				_add_reading(self._group(groups, reading.service, reading.team, by_team), reading)

		rows = [_finish(row) for row in groups.values()]
		rows.sort(key=lambda row: row["revenue"], reverse=True)
		return rows

	def _wanted(self, service: str) -> bool:
		return not self.filters.get("service") or service == self.filters["service"]

	@staticmethod
	def _group(groups: dict, service: str, team: str, by_team: bool) -> dict:
		key = (service, team if by_team else None)
		return groups.setdefault(key, _empty(service, team if by_team else None))

	def _load_rollups(self) -> list:
		"""Every live metered reading of the month, with what its billable part is worth at our price."""
		rollup = frappe.qb.DocType("Usage Rollup")
		query = (
			frappe.qb.from_(rollup)
			.select(
				rollup.team,
				rollup.resource_type,
				rollup.quantity,
				rollup.unit,
				rollup.currency,
				rollup.locked_allowance,
				rollup.locked_rate,
			)
			.where(rollup.superseded_by.isnull() | (rollup.superseded_by == ""))
			.where(rollup.period_start >= self.month.start)
			.where(rollup.period_start < frappe.utils.add_days(self.month.end, 1))
		)
		if self.filters.get("team"):
			query = query.where(rollup.team == self.filters["team"])
		return [self._reading(row) for row in query.run(as_dict=True)]

	def _reading(self, row) -> frappe._dict:
		family = self.month.families.get(row.resource_type)
		# Only a grandfathered postpaid reading locks the price it bills at; a live or prepaid one does not.
		priced = family and family.settlement_mode != "Prepaid Pack" and flt(row.locked_rate)
		value = None
		if priced and row.team not in self.internal:
			overage = max(0.0, flt(row.quantity) - flt(row.locked_allowance))
			value = to_inr(overage * flt(row.locked_rate), row.currency)
		return self._usage(row.team, row.resource_type, row.quantity, row.unit, value)

	def _load_ai_usage(self) -> list:
		"""AI usage of the month from Grove: tokens per team, and what each team spent at our price."""
		filters = {"add_on_service": AI_SERVICE}
		if self.filters.get("team"):
			filters["team"] = self.filters["team"]
		teams = frappe.get_all("Team Service", filters=filters, pluck="team")
		if not teams:
			return []

		try:
			usage = GroveClient.from_settings().get_usage(teams, month=self.month.start.strftime("%Y-%m"))
		except (GroveUnavailable, frappe.ValidationError):
			# A report must still open while Grove is down or AI is not set up; the message says AI is missing.
			self.ai_unread = True
			return []

		readings = []
		for team in teams:
			figures = usage.get(team) or {}
			if not flt(figures.get("tokens")) and not flt(figures.get("cost")):
				continue
			value = None if team in self.internal else to_inr(flt(figures.get("cost")), "USD")
			readings.append(self._usage(team, AI_RESOURCE_TYPE, figures.get("tokens"), "Nos", value))
		return readings

	def _usage(self, team: str, resource_type: str, quantity, unit, value) -> frappe._dict:
		return frappe._dict(
			team=team,
			service=self.month.service_of(resource_type),
			resource_type=resource_type,
			quantity=flt(quantity),
			unit=unit,
			value_inr=value,
			unit_cost=flt(self.month.unit_costs.get(resource_type)),
		)


def _empty(service: str, team: str | None) -> dict:
	return {
		"service": service,
		"team": team,
		"inr": "INR",
		"teams": set(),
		"unit": None,
		"revenue": 0.0,
		"billed": 0.0,
		"used": 0.0,
		"value": None,
		"line_cost": 0.0,
		"usage_cost": 0.0,
		"measured": False,
		"cost_missing": False,
		"unpriced_usd": False,
	}


def _add_line(row: dict, line) -> None:
	row["teams"].add(line.team)
	row["revenue"] += flt(line.revenue_inr)
	row["unpriced_usd"] = row["unpriced_usd"] or line.revenue_inr is None
	row["line_cost"] += flt(line.cost_inr)
	row["billed"] += _billed_units(line)
	row["unit"] = row["unit"] or (_("vCPU-months") if line.service == VM_SERVICE else line.unit)


def _add_reading(row: dict, reading) -> None:
	row["teams"].add(reading.team)
	row["measured"] = True
	row["used"] += reading.quantity
	row["usage_cost"] += reading.quantity * reading.unit_cost
	row["cost_missing"] = row["cost_missing"] or (reading.quantity > 0 and not reading.unit_cost)
	row["unit"] = row["unit"] or reading.unit
	if reading.value_inr is not None:
		row["value"] = flt(row["value"]) + reading.value_inr


def _billed_units(line) -> float:
	"""A VM bundle counts in vCPU-months, so plans of every size add up. A pack or other plan line
	is a price, not a quantity of the metered unit, so it adds no billed units."""
	if line.service == VM_SERVICE:
		return flt(line.vcpus) * (flt(line.days) + flt(line.hours) / 24) / 30
	if line.resource_type == "bundle" or line.plan:
		return 0.0
	return flt(line.quantity)


def _finish(row: dict) -> dict:
	row["customers"] = len(row.pop("teams"))
	if not row["measured"]:
		row["used"] = row["billed"]
	row["cost"] = row["usage_cost"] if row["measured"] else row["line_cost"]
	cost_per_unit = row["cost"] / row["used"] if row["used"] else 0.0
	row["free_units_cost"] = max(0.0, row["used"] - row["billed"]) * cost_per_unit if row["measured"] else 0.0
	row["not_billed"] = flt(max(0.0, row["value"] - row["revenue"]), 2) if row["value"] is not None else None
	row["gross_profit"] = row["revenue"] - row["cost"]
	row["margin"] = flt(100 * row["gross_profit"] / row["revenue"], 1) if row["revenue"] else None
	row["revenue_per_unit"] = flt(row["revenue"] / row["billed"], 4) if row["billed"] else None
	row["cost_per_unit"] = flt(cost_per_unit, 4) if row["used"] else None
	row["verdict"] = verdict(row)
	return row


def verdict(row: dict) -> str:
	"""What a service needs, the first that applies:
	1. Cost Not Set: it has usage but its Resource Type has no cost, so its margin is not real.
	2. Not Billed: its usage is worth more at our price than its invoices carry.
	3. Loss: it costs more than it earns.
	4. Thin Margin: it earns, but less than THIN_MARGIN_PERCENT of revenue.
	5. Profitable."""
	if row["cost_missing"]:
		return COST_NOT_SET
	if row["not_billed"] and row["not_billed"] > max(1.0, UNBILLED_TOLERANCE * flt(row["value"])):
		return NOT_BILLED
	if row["gross_profit"] < 0:
		return LOSS
	if row["margin"] is not None and row["margin"] < THIN_MARGIN_PERCENT:
		return THIN
	return PROFITABLE
