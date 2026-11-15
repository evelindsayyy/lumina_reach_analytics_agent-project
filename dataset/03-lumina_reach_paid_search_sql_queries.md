# Lumina Reach Paid Search: 20 Business SQL Queries

These are the twenty queries the analytics team answers most often (Q1–Q20).
They are grouped under the five question categories the Chief Analytics Office
uses (C1–C5). Every query is written in the **Snowflake dialect**, the dialect the
agent writes. Locally, the same text runs on the DuckDB file after sqlglot
transpiles it.

Conventions every query follows:

- **Time windows end on the reference date.** That is the last day of data
  (`v_reference_date.reference_date`, 2026-07-13), not the calendar date.
  "Last N days" means `report_date > DATEADD(day, -N, reference_date) AND
  report_date <= reference_date`. `daily_stats` and `search_term_report` cover 62
  days (2026-05-13 to 2026-07-13). Floodlight conversions go back to 2026-04-15.
- **Ratios are a sum over a sum.** CPA is `SUM(cost) / SUM(conversions)`, never
  `AVG(cpa)`. Impression shares are weighted by impressions:
  `SUM(share * impressions) / SUM(impressions)`.
- **There are three conversion sources, and they are never mixed.**
  `daily_stats.conversions` is the engine aggregate. The `conversion` table holds
  Floodlight events (`attribution_path` is built on it).
  `search_term_report.conversions` is the search term aggregate. Each query uses
  exactly one of them.
- **Budgets are versioned.** Always join the version in effect on each day,
  never every version.

| Category | Business question family | Queries |
| :--- | :--- | :--- |
| C1 | Attribution truth: which channels really drive conversions | Q12, Q13, Q14, Q18 |
| C2 | Budget efficiency: pacing, targets, budget-limited campaigns, trends | Q3, Q4, Q5, Q15, Q19 |
| C3 | Cross-engine and device efficiency | Q6, Q7, Q16 |
| C4 | Waste governance: zero-conversion spend, low quality, broad-match overflow | Q8, Q9, Q10, Q11, Q20 |
| C5 | Agency and portfolio structure | Q1, Q2, Q17 |

---

## C5. Agency and portfolio structure

### Q1. Portfolio overview by industry

**Business context:** the first slide of the CMO's quarterly review: how many
advertisers and campaigns each industry has, and what it spends.
**Difficulty:** medium (a four-join chain; counts must be `DISTINCT` because
`daily_stats` has one row per campaign, device and day).

```sql
SELECT i.industry_name,
       COUNT(DISTINCT a.advertiser_id) AS advertiser_count,
       COUNT(DISTINCT c.campaign_id) AS campaign_count,
       SUM(ds.cost) AS spend_60d
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN engine_account ea ON ea.engine_account_id = c.engine_account_id
JOIN advertiser a ON a.advertiser_id = ea.advertiser_id
JOIN industry i ON i.industry_id = a.industry_id
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -60, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY i.industry_name
ORDER BY spend_60d DESC
```

### Q2. Active clients by agency tier

**Business context:** how the network's book of business spreads across agency
tiers. Only current engagements count.
**Difficulty:** easy (the `is_active = 1` filter goes in the `LEFT JOIN`, so tiers
with no active client still appear).

```sql
SELECT ag.tier,
       COUNT(DISTINCT ag.agency_id) AS agencies,
       COUNT(DISTINCT ac.advertiser_id) AS active_clients
FROM agency ag
LEFT JOIN agency_client ac
  ON ac.agency_id = ag.agency_id AND ac.is_active = 1
GROUP BY ag.tier
ORDER BY active_clients DESC
```

### Q17. Top advertisers by spend, with their managing agency

**Business context:** which brands carry the network, and who manages them.
About a quarter of advertisers have no active agency, so their agency is empty.
**Difficulty:** medium (`LEFT JOIN`s keep self-managed advertisers).

```sql
SELECT a.advertiser_name,
       COALESCE(ag.agency_name, '(self-managed)') AS agency_name,
       SUM(ds.cost) AS spend_30d,
       SUM(ds.conversion_value) / NULLIF(SUM(ds.cost), 0) AS roas
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN engine_account ea ON ea.engine_account_id = c.engine_account_id
JOIN advertiser a ON a.advertiser_id = ea.advertiser_id
LEFT JOIN agency_client ac ON ac.advertiser_id = a.advertiser_id AND ac.is_active = 1
LEFT JOIN agency ag ON ag.agency_id = ac.agency_id
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY a.advertiser_name, ag.agency_name
ORDER BY spend_30d DESC
LIMIT 10
```

---

## C2. Budget efficiency

### Q3. Week-over-week CPA change, decomposed

**Business context:** an account manager is asked why CPA moved. CPA equals CPC
divided by the conversion rate, so the answer shows CPC, CTR and conversion rate
for both weeks and says which one moved.
**Difficulty:** hard (conditional aggregation over two windows in one pass).

```sql
SELECT a.advertiser_name,
       SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.cost, 0))
         / NULLIF(SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.conversions, 0)), 0) AS cpa_prior_week,
       SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.cost, 0))
         / NULLIF(SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.conversions, 0)), 0) AS cpa_this_week,
       SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.cost, 0))
         / NULLIF(SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.clicks, 0)), 0) AS cpc_prior_week,
       SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.cost, 0))
         / NULLIF(SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.clicks, 0)), 0) AS cpc_this_week,
       SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.conversions, 0))
         / NULLIF(SUM(IFF(ds.report_date <= DATEADD(day, -7, r.reference_date), ds.clicks, 0)), 0) AS cvr_prior_week,
       SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.conversions, 0))
         / NULLIF(SUM(IFF(ds.report_date > DATEADD(day, -7, r.reference_date), ds.clicks, 0)), 0) AS cvr_this_week
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN engine_account ea ON ea.engine_account_id = c.engine_account_id
JOIN advertiser a ON a.advertiser_id = ea.advertiser_id
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -14, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY a.advertiser_name
ORDER BY cpa_this_week / NULLIF(cpa_prior_week, 0) DESC NULLS LAST
LIMIT 10
```

### Q4. Campaign pacing against the budget in effect

**Business context:** which campaigns spent the most relative to their budget
over the last seven days.
**Difficulty:** hard. Budgets are versioned, so each day joins **only the
version in effect that day**, through a correlated subquery. A plain `JOIN
campaign_budget` counts every version and inflates the budget. `daily_stats` is
summed to one row per campaign and day first, so devices do not multiply the
budget either.

```sql
WITH campaign_day AS (
    SELECT ds.campaign_id, ds.report_date, SUM(ds.cost) AS cost
    FROM daily_stats ds
    CROSS JOIN v_reference_date r
    WHERE ds.report_date > DATEADD(day, -7, r.reference_date)
      AND ds.report_date <= r.reference_date
    GROUP BY ds.campaign_id, ds.report_date
), with_budget AS (
    SELECT cd.campaign_id, cd.cost,
           (SELECT cb.daily_budget
            FROM campaign_budget cb
            WHERE cb.campaign_id = cd.campaign_id
              AND cb.effective_date <= cd.report_date
            ORDER BY cb.effective_date DESC
            LIMIT 1) AS daily_budget
    FROM campaign_day cd
)
SELECT c.campaign_name,
       SUM(wb.cost) AS spend_7d,
       SUM(wb.daily_budget) AS budget_7d,
       SUM(wb.cost) / NULLIF(SUM(wb.daily_budget), 0) AS pacing_pct
FROM with_budget wb
JOIN campaign c ON c.campaign_id = wb.campaign_id
GROUP BY c.campaign_id, c.campaign_name
ORDER BY pacing_pct DESC
LIMIT 10
```

### Q5. Smart Bidding audit: campaigns over their Target CPA

**Business context:** is Smart Bidding delivering the CPA it was told to hit?
Only strategies that have a `target_cpa` are audited.
**Difficulty:** medium (`HAVING` on a ratio of sums).

```sql
SELECT c.campaign_name,
       bs.target_cpa,
       SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) AS actual_cpa,
       SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) / bs.target_cpa - 1 AS over_target_pct
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN bid_strategy bs ON bs.bid_strategy_id = c.bid_strategy_id
CROSS JOIN v_reference_date r
WHERE bs.target_cpa IS NOT NULL
  AND ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY c.campaign_id, c.campaign_name, bs.target_cpa
HAVING SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) > bs.target_cpa
ORDER BY over_target_pct DESC
LIMIT 20
```

### Q15. Budget-limited Search campaigns

**Business context:** the "easy money" list. These are Search campaigns that
lose impression share to budget while converting profitably, so more budget
buys more volume.
**Difficulty:** medium (the lost share is weighted by impressions, never
averaged).

```sql
SELECT c.campaign_name,
       SUM(ds.search_lost_is_budget * ds.impressions) / NULLIF(SUM(ds.impressions), 0) AS weighted_lost_is_budget,
       SUM(ds.conversion_value) / NULLIF(SUM(ds.cost), 0) AS roas,
       SUM(ds.cost) AS spend_30d
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
CROSS JOIN v_reference_date r
WHERE c.campaign_type = 'Search'
  AND ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY c.campaign_id, c.campaign_name
ORDER BY weighted_lost_is_budget DESC
LIMIT 10
```

### Q19. Daily spend, conversions and CPA trend

**Business context:** the line chart behind every anomaly conversation.
**Difficulty:** easy.

```sql
SELECT ds.report_date,
       SUM(ds.cost) AS cost,
       SUM(ds.conversions) AS conversions,
       SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) AS cpa
FROM daily_stats ds
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY ds.report_date
ORDER BY ds.report_date
```

---

## C3. Cross-engine and device efficiency

### Q6. Device-level CTR, CPA and ROAS

**Business context:** mobile takes most impressions, but which device converts
most cheaply?
**Difficulty:** medium (a window over an aggregate for each device's share of
impressions).

```sql
SELECT d.device_name,
       SUM(ds.impressions) AS impressions,
       SUM(ds.impressions) / SUM(SUM(ds.impressions)) OVER () AS impression_mix,
       SUM(ds.clicks) / NULLIF(SUM(ds.impressions), 0) AS ctr,
       SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) AS cpa,
       SUM(ds.conversion_value) / NULLIF(SUM(ds.cost), 0) AS roas
FROM daily_stats ds
JOIN device d ON d.device_id = ds.device_id
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY d.device_name
ORDER BY impressions DESC
```

### Q7. Google Ads vs Microsoft Advertising

**Business context:** should budget move to Microsoft? Its clicks are cheaper
but convert less often, so CPA ends up close. The answer shows both factors.
**Difficulty:** medium.

```sql
SELECT ea.engine,
       SUM(ds.cost) AS cost,
       SUM(ds.cost) / NULLIF(SUM(ds.clicks), 0) AS cpc,
       SUM(ds.clicks) / NULLIF(SUM(ds.impressions), 0) AS ctr,
       SUM(ds.conversions) / NULLIF(SUM(ds.clicks), 0) AS conversion_rate,
       SUM(ds.cost) / NULLIF(SUM(ds.conversions), 0) AS cpa,
       SUM(ds.conversion_value) / NULLIF(SUM(ds.cost), 0) AS roas
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN engine_account ea ON ea.engine_account_id = c.engine_account_id
CROSS JOIN v_reference_date r
WHERE ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY ea.engine
```

### Q16. Top-of-page impression share by engine (Search only)

**Business context:** position health. Impression shares exist only for Search
campaigns and are weighted by impressions.
**Difficulty:** medium (the filter and the weighting are both mandatory).

```sql
SELECT ea.engine,
       SUM(ds.search_top_impression_share * ds.impressions) / NULLIF(SUM(ds.impressions), 0) AS top_impression_share,
       SUM(ds.search_impression_share * ds.impressions) / NULLIF(SUM(ds.impressions), 0) AS impression_share
FROM daily_stats ds
JOIN campaign c ON c.campaign_id = ds.campaign_id
JOIN engine_account ea ON ea.engine_account_id = c.engine_account_id
CROSS JOIN v_reference_date r
WHERE c.campaign_type = 'Search'
  AND ds.report_date > DATEADD(day, -30, r.reference_date)
  AND ds.report_date <= r.reference_date
GROUP BY ea.engine
```

---

## C4. Waste governance

### Q8. Keywords that spent without converting

**Business context:** the weekly waste-recovery list. Keyword spend comes from
the search term report, so the conversions here are the search term source.
**Difficulty:** easy.

```sql
SELECT k.keyword_text,
       mt.match_type_name,
       SUM(st.cost) AS cost_30d,
       SUM(st.clicks) AS clicks_30d
FROM search_term_report st
JOIN keyword k ON k.keyword_id = st.keyword_id
JOIN match_type mt ON mt.match_type_id = k.match_type_id
CROSS JOIN v_reference_date r
WHERE st.report_date > DATEADD(day, -30, r.reference_date)
  AND st.report_date <= r.reference_date
GROUP BY k.keyword_id, k.keyword_text, mt.match_type_name
HAVING SUM(st.conversions) = 0
ORDER BY cost_30d DESC
LIMIT 20
```

### Q9. Low quality score keywords in high-spend campaigns

**Business context:** quality score 3 or lower raises CPC. The spend shown is the
**host campaign's** spend, named so, because `daily_stats` has no keyword grain.
**Difficulty:** medium.

```sql
WITH campaign_spend AS (
    SELECT ds.campaign_id, SUM(ds.cost) AS host_campaign_spend_30d
    FROM daily_stats ds
    CROSS JOIN v_reference_date r
    WHERE ds.report_date > DATEADD(day, -30, r.reference_date)
      AND ds.report_date <= r.reference_date
    GROUP BY ds.campaign_id
)
SELECT k.keyword_text,
       k.quality_score,
       c.campaign_name,
       cs.host_campaign_spend_30d
FROM keyword k
JOIN ad_group adg ON adg.ad_group_id = k.ad_group_id
JOIN campaign c ON c.campaign_id = adg.campaign_id
JOIN campaign_spend cs ON cs.campaign_id = c.campaign_id
WHERE k.quality_score <= 3
  AND k.status = 'Enabled'
ORDER BY cs.host_campaign_spend_30d DESC
LIMIT 20
```

### Q10. Broad-match overflow spend by campaign

**Business context:** search terms that matched no keyword of their ad group.
**Difficulty:** medium (`LEFT JOIN keyword` keeps the overflow rows, whose
`keyword_id` is NULL; an inner join silently drops exactly the rows asked about).

```sql
SELECT c.campaign_name,
       SUM(st.cost) AS overflow_cost_30d,
       SUM(st.clicks) AS overflow_clicks_30d
FROM search_term_report st
LEFT JOIN keyword k ON k.keyword_id = st.keyword_id
JOIN ad_group adg ON adg.ad_group_id = st.ad_group_id
JOIN campaign c ON c.campaign_id = adg.campaign_id
CROSS JOIN v_reference_date r
WHERE k.keyword_id IS NULL
  AND st.report_date > DATEADD(day, -30, r.reference_date)
  AND st.report_date <= r.reference_date
GROUP BY c.campaign_id, c.campaign_name
ORDER BY overflow_cost_30d DESC
LIMIT 10
```

### Q11. Most wasteful search terms

**Business context:** candidates for negative keywords.
**Difficulty:** easy.

```sql
SELECT st.search_term,
       SUM(st.cost) AS cost_30d,
       SUM(st.clicks) AS clicks_30d
FROM search_term_report st
CROSS JOIN v_reference_date r
WHERE st.report_date > DATEADD(day, -30, r.reference_date)
  AND st.report_date <= r.reference_date
GROUP BY st.search_term
HAVING SUM(st.conversions) = 0
ORDER BY cost_30d DESC
LIMIT 20
```

### Q20. Search term coverage by match type

**Business context:** a data-quality view. It shows how much search term spend
is matched to a keyword and how much is overflow, for each match type.
**Difficulty:** easy.

```sql
SELECT mt.match_type_name,
       SUM(st.cost) AS cost_30d,
       SUM(IFF(st.keyword_id IS NULL, st.cost, 0)) / NULLIF(SUM(st.cost), 0) AS overflow_cost_share
FROM search_term_report st
JOIN match_type mt ON mt.match_type_id = st.match_type_id
CROSS JOIN v_reference_date r
WHERE st.report_date > DATEADD(day, -30, r.reference_date)
  AND st.report_date <= r.reference_date
GROUP BY mt.match_type_name
ORDER BY cost_30d DESC
```

---

## C1. Attribution truth

All attribution questions use the Floodlight event source: the `conversion`
table, the `attribution_path` built on it, and the `mv_attribution_six_models`
view. `data_driven_credit` is a **non-production simulation, illustrative only**,
and every answer that shows it says so.

### Q12. First-touch vs last-touch channel mix

**Business context:** last-click reporting gives upper-funnel channels no
credit. This shows how often each channel opens a path compared with how often
it closes one.
**Difficulty:** medium.

```sql
SELECT ch.channel_name,
       ch.funnel_stage,
       SUM(IFF(ap.touch_index = 1, 1, 0)) AS first_touch_conversions,
       SUM(IFF(ap.touch_index = ap.path_length, 1, 0)) AS last_touch_conversions
FROM attribution_path ap
JOIN channel ch ON ch.channel_id = ap.channel_id
GROUP BY ch.channel_name, ch.funnel_stage
ORDER BY first_touch_conversions DESC
```

### Q13. Conversion path length distribution

**Business context:** is multi-touch attribution worth operationalising? Only
if paths are long enough for it to matter.
**Difficulty:** easy (one row per conversion: `COUNT(DISTINCT conversion_id)`).

```sql
SELECT ap.path_length,
       COUNT(DISTINCT ap.conversion_id) AS conversions,
       COUNT(DISTINCT ap.conversion_id) / SUM(COUNT(DISTINCT ap.conversion_id)) OVER () AS share
FROM attribution_path ap
GROUP BY ap.path_length
ORDER BY ap.path_length
```

### Q14. Channel value under all six attribution models

**Business context:** the headline deliverable. It shows, side by side, how much
conversion value each channel earns under last-click, first-click, linear, time
decay, position-based and (simulated) data-driven attribution.
**Difficulty:** easy on the view. Without the view it is a `SUM(credit *
conversion_value)` per model.

```sql
SELECT m.channel_name,
       m.attribution_model,
       m.attributed_value
FROM mv_attribution_six_models m
ORDER BY m.channel_name, m.attribution_model
```

### Q18. Time from first touch to conversion, by first-touch channel

**Business context:** how long each channel's journeys take to pay off. No
journey exceeds the 90-day maximum lookback window.
**Difficulty:** medium.

```sql
SELECT ch.channel_name,
       COUNT(*) AS conversions,
       AVG(DATEDIFF(hour, ap.touch_time, c.conversion_time)) AS avg_hours_to_conversion,
       MAX(DATEDIFF(day, ap.touch_time, c.conversion_time)) AS max_days_to_conversion
FROM attribution_path ap
JOIN conversion c ON c.conversion_id = ap.conversion_id
JOIN channel ch ON ch.channel_id = ap.channel_id
WHERE ap.touch_index = 1
GROUP BY ch.channel_name
ORDER BY avg_hours_to_conversion DESC
```
