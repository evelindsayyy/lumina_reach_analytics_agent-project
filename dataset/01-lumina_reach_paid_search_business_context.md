# Lumina Reach Paid Search: Business Context

## 1. Company profile

**Lumina Reach Media Group** (fictional) is a media agency holding company
headquartered in Chicago, Illinois. It does not serve advertisers directly.
Instead, it runs a network of **15 member agencies**, graded by service
capability into four tiers:

| Tier | Agencies | Typical client |
| :--- | ---: | :--- |
| Platinum | 2 | the largest national brands, multi-engine, Smart Bidding at scale |
| Gold | 4 | national and large regional brands |
| Silver | 5 | regional brands |
| Standard | 4 | smaller brands, simpler account structures |

The network runs paid search for **80 advertiser brands** in 10 industries:
Retail, Travel, Financial Services, Healthcare, Auto, Insurance, B2B SaaS,
Education, Real Estate and Restaurants. About 80% of the advertisers are
managed by a member agency. The other 20% run their search in-house but still
report through the group's platform; these are called **self-managed**.

The **Central Analytics Office (CAO)**, about ten analysts reporting to the
group CMO, answers cross-portfolio questions:

- quarterly reviews for the CMO;
- portfolio diagnostics for agency account managers;
- attribution analysis for brand campaign managers.

The analytics agent exists to answer the CAO's standard questions directly,
for people who do not write SQL.

## 2. Business model

The group earns an **agency fee on managed spend**:

- **Percentage fee:** most engagements pay 8% to 20% of the paid search spend
  under management (`agency_client.fee_percentage`).
- **Flat fee:** a few pay a fixed yearly amount instead
  (`agency_client.annual_flat_fee`).

So revenue depends on two things:

1. **How much spend the network manages.** Tens of millions of dollars a month
   across Google Ads and Microsoft Advertising.
2. **How well it manages it.** Lower CPA and higher ROAS keep clients renewing
   and growing.

Every budget misallocated because of a misleading attribution model eventually
shows up as lost fee revenue. That is why attribution and efficiency questions
matter most.

## 3. Industry primer

- **Search engines and accounts.** An advertiser has one account per engine
  (`engine_account`). Google Ads is the larger engine. Microsoft Advertising
  has cheaper clicks (CPC about 80% of Google's) but converts less often (about
  12% lower), so CPAs end up close.
- **Account structure.** An account holds campaigns. A campaign holds ad
  groups. An ad group holds keywords (what you bid on) and text ads (what is
  shown). A campaign is Search, Shopping or Display.
- **Match types.** *Exact* matches the query closely. *Phrase* matches queries
  containing the phrase. *Broad* matches related queries. Broad match can serve
  on searches no keyword of the ad group covers. That is **broad-match
  overflow**: the search term report shows those terms with no keyword.
- **Bidding.** Manual CPC and Enhanced CPC are bid by people. *Smart Bidding*
  (Maximize Conversions, Target CPA, Target ROAS) lets the engine set every bid
  toward a target. Analysts now spend less time setting bids and more time
  checking whether the machine hits its target.
- **Budgets.** A campaign has a daily budget that changes over time
  (`campaign_budget` holds every version with its `effective_date`). When the
  budget binds, the campaign misses auctions it could have won. That shows up
  as **impression share lost to budget**.
- **Quality score** (1 to 10) is the engine's rating of a keyword's expected
  CTR, ad relevance and landing page. A low score raises the price of every
  click.
- **Devices.** Mobile takes about 60% of impressions. Desktop converts best and
  has the lowest CPA.
- **Conversion tracking.** Engines report their own conversions (aggregated in
  `daily_stats`). Independently, **Floodlight** tags (`floodlight_tag`) on
  advertiser sites record each conversion event (`conversion`) with the
  touchpoints that led to it (`attribution_path`). Each tag has a lookback
  window of 30, 60 or 90 days.
- **Attribution.** A conversion path has 2 to 6 touches across six channels
  (Paid Search, Display, Paid Social, Email, Organic Search, Direct).
  Upper-funnel channels (Display, Paid Social) tend to open paths. Lower-funnel
  ones close them. Last-click attribution gives all the credit to the closer,
  so it systematically under-credits the upper funnel. Comparing models side by
  side is how the CMO quantifies that bias.
- **Market context.** Three forces reshape the business:
  - automation (Smart Bidding) moves analysts from bidding to auditing;
  - signal loss (third-party cookie deprecation, Apple ATT) makes deterministic
    attribution less trustworthy;
  - antitrust scrutiny of Google's search dominance unsettles the default
    engine mix.

## 4. Glossary

| Term | Meaning |
| :--- | :--- |
| Impression | One showing of an ad. |
| Click | One click on an ad. |
| Cost / spend | What the clicks cost, in USD. |
| Conversion | A valuable action (purchase, lead, sign-up, booking). See the three sources below. |
| Conversion value | The USD value of the conversions. |
| CTR | Click-through rate: clicks / impressions. |
| CPC | Cost per click: cost / clicks. |
| CVR | Conversion rate: conversions / clicks. |
| CPA | Cost per acquisition: cost / conversions. Equals CPC / CVR. |
| ROAS | Return on ad spend: conversion value / cost. |
| Impression share (IS) | Impressions won / impressions eligible for. Search campaigns only. |
| Top impression share | Share of impressions shown above the organic results. |
| Lost IS (budget) | Share of eligible impressions missed because the budget ran out. |
| Lost IS (rank) | Share missed because of low ad rank (bid × quality). |
| Pacing | Spend / budget in effect over a period; above 100% means overspending. |
| Target CPA / Target ROAS | The goal a Smart Bidding strategy optimizes toward. |
| Quality score | Engine rating of a keyword, 1 to 10. |
| Broad-match overflow | Spend on search terms that matched no keyword of the ad group. |
| Floodlight | The site tag that records conversion events independently of the engines. |
| Lookback window | How far back before a conversion a touch can still get credit (30, 60 or 90 days). |
| Path length | Number of touches before a conversion (2 to 6 here). |
| Reference date | The last day of data, 2026-07-13: where every time window ends. |
| Self-managed advertiser | An advertiser with no active agency engagement. |

## 5. Key metric formulas

Every ratio is a **sum over a sum** across the rows being aggregated, never an
average of per-row ratios:

| Metric | Formula |
| :--- | :--- |
| CTR | `SUM(clicks) / SUM(impressions)` |
| CPC | `SUM(cost) / SUM(clicks)` |
| CVR | `SUM(conversions) / SUM(clicks)` |
| CPA | `SUM(cost) / SUM(conversions)` |
| ROAS | `SUM(conversion_value) / SUM(cost)` |
| Weighted impression share | `SUM(search_impression_share * impressions) / SUM(impressions)` (same for top share and lost share) |
| Pacing | `SUM(cost) / SUM(daily_budget in effect on each day)`, with one budget per campaign per day |
| Over-target % | `actual CPA / target_cpa - 1` |
| Channel value under a model | `SUM(model_credit * conversion.conversion_value)` over `attribution_path` |
| Agency fee (percentage) | `SUM(cost) * fee_percentage` over the advertiser's managed spend |

### The six attribution models

| Model | Credit rule |
| :--- | :--- |
| Last-click | 100% to the last touch. |
| First-click | 100% to the first touch. |
| Linear | `1 / path_length` to every touch. |
| Time decay | More credit to touches closer to the conversion (7-day half-life). |
| Position-based | 40% first, 40% last, 20% spread over the middle touches (50/50 for two touches). |
| Data-driven (simulated) | **A non-production simulation, illustrative only.** Not the output of a fitted model; always say so. |

### The three conversion sources

| Source | Where | Counts |
| :--- | :--- | :--- |
| Engine aggregate | `daily_stats.conversions`, `daily_stats.conversion_value` | what the engines report, by campaign, device and day |
| Floodlight events | `conversion` (+ `attribution_path`, `mv_attribution_six_models`) | one row per conversion event, the subject of attribution |
| Search term aggregate | `search_term_report.conversions` | conversions credited to each search term |

They measure different things at different grains. **They are never added,
joined row to row, or compared as if they were the same number.** An answer
about conversions always says which source it used.
