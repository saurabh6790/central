# Billing reports and dashboards

## Purpose

This page lists every billing report and Insights dashboard, and the question each one answers. Use it to find the right view when you monitor billing or investigate a problem.

## Where to find them

- Desk reports: the Billing sidebar in Desk, or `/desk/query-report/<Report Name>`. All reports need the System Manager role.
- Insights dashboards: open the Billing workbook in Insights. The app ships the workbook from `central/billing/insights_workbook/billing/billing.json`, and `bench migrate` installs it.

## Rules every report follows

- Money is shown per currency. A report never adds INR and USD in one column, total or card.
- Bare metal cost is in INR. A USD amount counts toward a margin only when you enter a USD to INR rate in the report filter.

## Insights dashboards

| Dashboard | Use it to |
|---|---|
| Billing Health | See the state of billing at a glance: monthly run rate, outstanding and overdue receivables, credit held in wallets, payment success, failed and stuck payments, stuck webhooks, accounting sync failures, held invoices and past due subscriptions. Charts show invoicing and collection by month, payment attempts by status, success by gateway, webhook lag, receivables aging, credit flow and the teams with the most outstanding. |
| Unit Economics | See what the bare metal costs and who uses it: metal and idle cost, vCPUs allocated against capacity, servers by funding class, the cost of unpaid servers, capacity per region and the teams that carry the most metal cost. |

## Inventory and unit economics reports

| Report | Question it answers |
|---|---|
| Region Capacity | How much bare metal does each region have, how much do live servers use (vCPU, memory and disk), and what does the idle part cost? |
| Server Inventory | Which servers are live, which team owns each one, who funds it (Internal, Trial, Paid or Free Credits), what does it list at, what does it earn and what is its margin? |
| Unit Economics | Grouped by funding class, region or team: what is the metal cost, the list value, the cash revenue and the margin? The Idle Capacity row makes the costs add up to the full metal bill. |

### How cost and funding are worked out

- A region's monthly cost is the sum of `cost_per_month_inr` on its Active Metal Servers. Cost per vCPU is that cost divided by the region's vCPUs. A live server carries its vCPUs times the cost per vCPU.
- A live server is any Virtual Machine that is not Terminated or Failed.
- Funding is checked in this order, and the first match wins:
  1. Internal: the team's Tax Profile is internal.
  2. Trial: the server runs a free trial site.
  3. Paid: the team has an active payment method, bought credit, or paid an invoice.
  4. Free Credits: anything else. The team runs on promotional credit.
- Only a Paid server earns cash revenue. The others show their list value, which is what the company gives away.
- The readiness check R1 in Billing Invariant Violations flags a region that runs servers but has no priced Metal Server.

## Revenue reports

| Report | Question it answers |
|---|---|
| Invoice Register | Which invoices were raised, for whom, for how much, and in which status? |
| Collection Outlook | Which teams are about to be suspended for non-payment, and on what date? |
| AR Collections Aging | How much is still to collect, and how many days past due is it? |
| MRR and YTD Revenue | What is the monthly recurring revenue, and the revenue for the year so far? |
| Billing Projection | What is a group of teams about to be billed, from the latest projection batch? |
| Atlas-based Revenue | How much revenue does each Atlas region earn, and what share of its currency's total is that? |
| Services Revenue | How much revenue comes from metered services such as AI tokens, email and PDF? |
| Cluster-wise Revenue | How much revenue does each region earn? |
| Refunds Report | Which refunds were made, to where, and for how much? |

## Payment reports

| Report | Question it answers |
|---|---|
| Failed Payments | Which payment attempts failed, and why? |
| Gateway Payment Success Ratio | What share of attempts succeed on each gateway, month by month? |
| Payment Method Mix | Which payment methods do teams use, in which state, and how many need authorisation again? |

## Credit reports

| Report | Question it answers |
|---|---|
| Credit Wallet Movements | What went in and out of each wallet, and why? |
| Team Credit Balance | How much credit does each team hold now? |

## Usage and growth reports

| Report | Question it answers |
|---|---|
| New Signups | Which teams signed up, and how far did each get: billing profile, payment method, first paid invoice? |
| Trial Sites | How many trial sites started per product and month, how did they end, and what did they cost? |
| Monthly Usage vs Invoiced | Did every metered unit reach an invoice? |
| Metered Add-ons | What does each metered add-on include, and what does it charge above that, per currency? |

## Health reports

| Report | Question it answers |
|---|---|
| Billing Invariant Violations | Which billing rules are broken now? This covers money invariants and readiness checks, such as unpriced subscriptions or unbilled running servers. Use the Summary view for a count per check. |
| Dunning Recovery | Of the invoices that became overdue, how many were paid later? |
| Involuntary Churn | Which teams were suspended for non-payment, and which came back? |
| Internal Usage and Waivers | What did internal teams use, and how much was waived? |
| Webhook Lag | How long do gateway webhooks take from receipt to processing? |
