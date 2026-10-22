# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._columns import column, inr
from central.billing.report._services import (
	COST_NOT_SET,
	LOSS,
	NOT_BILLED,
	THIN,
	THIN_MARGIN_PERCENT,
	ServiceMonth,
)


def execute(filters: dict | None = None):
	"""Which services to push, fix, reprice or drop: usage, revenue, provider cost, margin and a verdict per service.

	Price per unit reads per billed unit, cost per unit per used unit, in the service's own unit
	(vCPU-month for VMs, GB, token, email)."""
	filters = filters or {}
	month = ServiceMonth(filters)
	by_team = (filters.get("group_by") or "Service") == "Team"
	rows = month.rows(by_team)
	return get_columns(by_team), rows, _message(month, rows), _chart(rows), _summary(rows)


def _message(month: ServiceMonth, rows: list[dict]) -> str:
	text = _(
		"Billed for {0}. Cost is the bare metal share for VMs, and used units times the Resource Type's cost per unit for the rest, billed or not. Thin Margin is below {1}%."
	).format(month.month.start.strftime("%B %Y"), THIN_MARGIN_PERCENT)
	if month.ai_unread:
		text += " " + _("AI usage is left out: Grove could not be read.")
	if any(row["unpriced_usd"] for row in rows):
		text += " " + _("USD revenue is left out: set the USD to INR rate in Billing Settings.")
	return text


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["service"] for row in rows],
			"datasets": [
				{"name": _("Revenue"), "values": [flt(row["revenue"], 2) for row in rows]},
				{"name": _("Provider Cost"), "values": [flt(row["cost"], 2) for row in rows]},
				{"name": _("Gross Profit"), "values": [flt(row["gross_profit"], 2) for row in rows]},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	revenue = sum(row["revenue"] for row in rows)
	profit = sum(row["gross_profit"] for row in rows)
	not_billed = sum(flt(row["not_billed"]) for row in rows)
	flagged = sum(row["verdict"] in (COST_NOT_SET, NOT_BILLED, LOSS) for row in rows)
	return [
		{"label": _("Revenue (INR)"), "value": revenue, "datatype": "Currency", "currency": "INR"},
		{
			"label": _("Gross Profit (INR)"),
			"value": profit,
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Green" if profit >= 0 else "Red",
		},
		{
			"label": _("Gross Margin"),
			"value": f"{flt(100 * profit / revenue, 1) if revenue else 0}%",
			"datatype": "Data",
		},
		{
			"label": _("Used but Not Billed (INR)"),
			"value": not_billed,
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Red" if not_billed else "Green",
		},
		{
			"label": _("Need Action"),
			"value": flagged,
			"datatype": "Int",
			"indicator": "Red" if flagged else "Green",
		},
		{
			"label": _("Thin Margin"),
			"value": sum(row["verdict"] == THIN for row in rows),
			"datatype": "Int",
		},
	]


def get_columns(by_team: bool) -> list[dict]:
	columns = [column(_("Service"), "service", "Data", 160)]
	if by_team:
		columns.append(column(_("Team"), "team", "Link", 130, options="Team"))
	return [
		*columns,
		column(_("Verdict"), "verdict", "Data", 110),
		column(_("Customers"), "customers", "Int", 90),
		column(_("Used"), "used", "Float", 110, precision=2),
		column(_("Billed"), "billed", "Float", 110, precision=2),
		column(_("Unit"), "unit", "Data", 100),
		inr(_("Usage Value (INR)"), "value", 130),
		inr(_("Revenue (INR)"), "revenue"),
		inr(_("Used but Not Billed (INR)"), "not_billed", 150),
		inr(_("Provider Cost (INR)"), "cost", 130),
		inr(_("Cost of Free Units (INR)"), "free_units_cost", 150),
		inr(_("Gross Profit (INR)"), "gross_profit"),
		column(_("Margin %"), "margin", "Percent", 80),
		column(_("Price per Unit (INR)"), "revenue_per_unit", "Currency", 130, options="inr"),
		column(_("Cost per Unit (INR)"), "cost_per_unit", "Currency", 130, options="inr"),
	]
