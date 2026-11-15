# Lumina Reach Paid Search: Dataset Summary

**Lumina Reach Media Group** is a fictional media agency holding company based in
Chicago. Its network has 15 member agencies in four tiers (Platinum, Gold,
Silver, Standard). Together they run paid search for 80 advertiser brands across
10 industries, on Google Ads and Microsoft Advertising. The group earns a fee of
8% to 20% of the spend it manages, so its revenue depends on two things: how much
spend it manages, and how well it manages it. The Central Analytics Office (CAO)
answers the network's reporting questions. This dataset is that office's
SA360-style warehouse.

**Size:** 21 tables and 2 views, 557,614 rows (seed 42), in one schema,
`lumina_reach`. The largest tables:

| Table | Rows | Grain |
| :--- | ---: | :--- |
| `search_term_report` | 311,799 | search term × ad group × day |
| `daily_stats` | 164,796 | campaign × device × day |
| `keyword` | 33,399 | keyword bid |
| `text_ad` | 18,550 | ad |
| `attribution_path` | 15,555 | touchpoint of a conversion path |
| `conversion` | 5,000 | Floodlight conversion event |

**Time:** the data ends on a fixed **reference date, 2026-07-13**, exposed as the
`v_reference_date` view. Every "last N days" ends on it, never on the calendar.
Performance data covers 62 days; Floodlight conversions cover 90.

**What it answers** falls into five categories, with 20 reference queries in
`03-lumina_reach_paid_search_sql_queries.md`:

- **C1 Attribution truth:** channel value under six attribution models,
  first-touch vs last-touch mix, path lengths, time to conversion.
- **C2 Budget efficiency:** pacing against the budget in effect, Smart Bidding
  target audits, budget-limited campaigns, CPA trends and week-over-week change.
- **C3 Cross-engine and device efficiency:** Google vs Microsoft, Mobile vs
  Desktop vs Tablet, top-of-page impression share.
- **C4 Waste governance:** zero-conversion keywords and search terms, low
  quality scores, broad-match overflow.
- **C5 Agency and portfolio structure:** industries, agency tiers, top
  advertisers and who manages them.

**Three traps the data is built to contain.** An analyst, or an agent, must not
fall into them:

1. **"Conversions" has three sources that never add up.** `daily_stats` holds
   engine-reported totals. `conversion` and `attribution_path` hold Floodlight
   events. `search_term_report` holds search term totals.
2. **Budgets are versioned.** Join the version in effect on each day, or spend
   is compared against a budget counted several times.
3. **`data_driven_credit` is a simulation.** It is illustrative only, and every
   answer that uses it says so.
