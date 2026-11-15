# -*- coding: utf-8 -*-

"""
Lumina Reach paid search warehouse generator.

Lumina Reach Media Group is a fictional media agency holding company in
Chicago: 15 member agencies run paid search for 80 advertisers on Google Ads
and Microsoft Advertising. This script builds its SA360-style warehouse, 21
tables and about 558K rows, as one DuckDB file next to it:
``dataset/lumina_reach_paid_search.duckdb``, schema ``lumina_reach``.

The data is synthetic and deterministic: one seed gives one warehouse, and
every relative window is anchored on ``REFERENCE_DATE`` (2026-07-13), never on
today. It is shaped to carry the facts the analyses rely on (see the summary
and the ER document of this dataset):

- conversion path lengths 2 to 6 with weights ``[40, 30, 15, 10, 5]``;
- every touch inside its tag's lookback window, at most 90 days;
- Microsoft CPC about 80% of Google's, conversion rate about 12% lower,
  so the two CPAs are close;
- Mobile takes about 60% of impressions while Desktop has the lowest CPA;
- several budget versions per campaign (a plain join double counts);
- broad-match overflow search terms with no keyword (``keyword_id`` NULL);
- upper-funnel channels under-credited by last-click attribution;
- a ``data_driven_credit`` column that is a simulation, not a real model;
- three sources of "conversions" that must never be added together.

Run it, never edit it to fit a question::

    python dataset/04-lumina_reach_paid_search_data_generator.py [--seed 42] [--out PATH]

Dependencies: the standard library and duckdb (``requirements.txt``).
"""

from __future__ import annotations

import csv
import random
import argparse
import tempfile
import dataclasses
import datetime as dt
from pathlib import Path

#: The schema every table and view lives in: SCHEMA_NAME in .env.defaults.
SCHEMA_NAME = "lumina_reach"

#: Where the warehouse is written by default.
DEFAULT_OUT = Path(__file__).absolute().parent / "lumina_reach_paid_search.duckdb"


# =============================================================================
# Tables
# =============================================================================
@dataclasses.dataclass(frozen=True)
class Column:
    """
    One column of a table.
    """

    # fmt: off
    name: str = dataclasses.field()  #: Column name, lower snake case.
    type: str = dataclasses.field()  #: Portable SQL type: INTEGER, DOUBLE, VARCHAR, DATE, TIMESTAMP, BOOLEAN.
    description: str = dataclasses.field()  #: What it means, for the model and the docs.
    sensitive: bool = dataclasses.field(default=False)  #: Internal contact data the agent must not select.
    nullable: bool = dataclasses.field(default=False)  #: Whether NULL is a legitimate value.
    # fmt: on


@dataclasses.dataclass(frozen=True)
class Table:
    """
    One business table.
    """

    # fmt: off
    name: str = dataclasses.field()  #: Table name, lower snake case.
    kind: str = dataclasses.field()  #: dimension, organization, structure, or fact.
    description: str = dataclasses.field()  #: What one row is.
    columns: tuple[Column, ...] = dataclasses.field()  #: In storage order.
    primary_key: tuple[str, ...] = dataclasses.field()  #: Column names of the primary key.
    # fmt: on

    @property
    def column_names(self) -> list[str]:
        """
        The column names, in storage order.
        """
        return [column.name for column in self.columns]

    def get_column(self, name: str) -> Column:
        """
        The column called ``name``.

        :raises KeyError: no such column.
        """
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"table {self.name!r} has no column {name!r}")


def _c(name: str, type_: str, description: str, **kwargs) -> Column:
    return Column(name=name, type=type_, description=description, **kwargs)


# fmt: off
TABLES: tuple[Table, ...] = (
    # --- dimensions ---------------------------------------------------------
    Table("industry", "dimension", "An IAB industry vertical of advertisers.", (
        _c("industry_id", "INTEGER", "Industry ID."),
        _c("industry_name", "VARCHAR", "Industry name, such as Retail or B2B SaaS."),
    ), ("industry_id",)),
    Table("region", "dimension", "A US Census division where an agency or advertiser is based.", (
        _c("region_id", "INTEGER", "Region ID."),
        _c("region_name", "VARCHAR", "Region name, such as East North Central."),
    ), ("region_id",)),
    Table("bid_strategy_type", "dimension", "A bidding strategy type.", (
        _c("bid_strategy_type_id", "INTEGER", "Bid strategy type ID."),
        _c("type_name", "VARCHAR", "Manual CPC, Enhanced CPC, Maximize Clicks, Maximize Conversions, Target CPA, or Target ROAS."),
        _c("is_smart_bidding", "BOOLEAN", "Whether the engine sets bids automatically."),
    ), ("bid_strategy_type_id",)),
    Table("match_type", "dimension", "A keyword match type.", (
        _c("match_type_id", "INTEGER", "Match type ID."),
        _c("match_type_name", "VARCHAR", "Exact, Phrase, or Broad."),
    ), ("match_type_id",)),
    Table("device", "dimension", "A device class.", (
        _c("device_id", "INTEGER", "Device ID."),
        _c("device_name", "VARCHAR", "Mobile, Desktop, or Tablet."),
    ), ("device_id",)),
    Table("channel", "dimension", "A marketing channel of a touchpoint in a conversion path.", (
        _c("channel_id", "INTEGER", "Channel ID."),
        _c("channel_name", "VARCHAR", "Paid Search, Display, Paid Social, Email, Organic Search, or Direct."),
        _c("funnel_stage", "VARCHAR", "upper, mid, or lower funnel."),
    ), ("channel_id",)),
    # --- organization -------------------------------------------------------
    Table("agency", "organization", "A member agency of the Lumina Reach network.", (
        _c("agency_id", "INTEGER", "Agency ID."),
        _c("agency_name", "VARCHAR", "Agency name."),
        _c("tier", "VARCHAR", "Platinum, Gold, Silver, or Standard."),
        _c("region_id", "INTEGER", "Region of the agency's head office."),
        _c("founded_year", "INTEGER", "Year founded."),
        _c("contact_email", "VARCHAR", "Business contact email.", sensitive=True),
        _c("contact_phone", "VARCHAR", "Business contact phone.", sensitive=True),
    ), ("agency_id",)),
    Table("advertiser", "organization", "An advertiser brand whose paid search Lumina Reach reports on.", (
        _c("advertiser_id", "INTEGER", "Advertiser ID."),
        _c("advertiser_name", "VARCHAR", "Brand name."),
        _c("industry_id", "INTEGER", "Industry of the brand."),
        _c("region_id", "INTEGER", "Region of the brand's head office."),
        _c("website_url", "VARCHAR", "Brand website.", sensitive=True),
    ), ("advertiser_id",)),
    Table("agency_client", "organization", "Which agency manages which advertiser, and its fee; about 80% of advertisers have one.", (
        _c("agency_id", "INTEGER", "Managing agency."),
        _c("advertiser_id", "INTEGER", "Managed advertiser."),
        _c("start_date", "DATE", "First day of the engagement."),
        _c("end_date", "DATE", "Last day of the engagement; NULL while active.", nullable=True),
        _c("fee_type", "VARCHAR", "percentage or flat."),
        _c("fee_percentage", "DOUBLE", "Fee as a fraction of managed spend (0.08 to 0.20); NULL for a flat fee.", nullable=True),
        _c("annual_flat_fee", "DOUBLE", "Yearly flat fee in USD; NULL for a percentage fee.", nullable=True),
        _c("is_active", "INTEGER", "1 if the engagement is current, else 0. Portfolio questions filter is_active = 1."),
    ), ("agency_id", "advertiser_id")),
    # --- account structure --------------------------------------------------
    Table("engine_account", "structure", "An advertiser's account on one search engine.", (
        _c("engine_account_id", "INTEGER", "Engine account ID."),
        _c("advertiser_id", "INTEGER", "Owning advertiser."),
        _c("engine", "VARCHAR", "Google Ads or Microsoft Advertising."),
        _c("account_name", "VARCHAR", "Account name."),
    ), ("engine_account_id",)),
    Table("bid_strategy", "structure", "A portfolio bid strategy of an advertiser.", (
        _c("bid_strategy_id", "INTEGER", "Bid strategy ID."),
        _c("advertiser_id", "INTEGER", "Owning advertiser."),
        _c("bid_strategy_type_id", "INTEGER", "Its type."),
        _c("strategy_name", "VARCHAR", "Strategy name."),
        _c("target_cpa", "DOUBLE", "Target cost per acquisition in USD; set only for Target CPA strategies.", nullable=True),
        _c("target_roas", "DOUBLE", "Target return on ad spend (value / cost); set only for Target ROAS strategies.", nullable=True),
    ), ("bid_strategy_id",)),
    Table("campaign", "structure", "A campaign in an engine account.", (
        _c("campaign_id", "INTEGER", "Campaign ID."),
        _c("engine_account_id", "INTEGER", "Engine account."),
        _c("bid_strategy_id", "INTEGER", "Bid strategy in use."),
        _c("campaign_name", "VARCHAR", "Campaign name."),
        _c("campaign_type", "VARCHAR", "Search, Shopping, or Display."),
        _c("status", "VARCHAR", "Enabled or Paused."),
        _c("start_date", "DATE", "Launch date."),
    ), ("campaign_id",)),
    Table("campaign_budget", "structure", "A version of a campaign's daily budget, valid from effective_date until the next version. A campaign can have several versions: join the version in effect on each report_date, never all of them.", (
        _c("budget_id", "INTEGER", "Budget version ID."),
        _c("campaign_id", "INTEGER", "Campaign."),
        _c("daily_budget", "DOUBLE", "Daily budget in USD."),
        _c("effective_date", "DATE", "First day this version applies."),
    ), ("budget_id",)),
    Table("ad_group", "structure", "An ad group of a campaign.", (
        _c("ad_group_id", "INTEGER", "Ad group ID."),
        _c("campaign_id", "INTEGER", "Campaign."),
        _c("ad_group_name", "VARCHAR", "Ad group name."),
        _c("status", "VARCHAR", "Enabled or Paused."),
    ), ("ad_group_id",)),
    Table("keyword", "structure", "A keyword bid in an ad group.", (
        _c("keyword_id", "INTEGER", "Keyword ID."),
        _c("ad_group_id", "INTEGER", "Ad group."),
        _c("keyword_text", "VARCHAR", "Keyword text."),
        _c("match_type_id", "INTEGER", "Match type."),
        _c("max_cpc", "DOUBLE", "Max cost per click bid in USD."),
        _c("quality_score", "INTEGER", "Engine quality score, 1 to 10."),
        _c("status", "VARCHAR", "Enabled or Paused."),
    ), ("keyword_id",)),
    Table("text_ad", "structure", "A text ad in an ad group.", (
        _c("ad_id", "INTEGER", "Ad ID."),
        _c("ad_group_id", "INTEGER", "Ad group."),
        _c("headline", "VARCHAR", "Headline."),
        _c("description", "VARCHAR", "Description line."),
        _c("status", "VARCHAR", "Enabled or Paused."),
    ), ("ad_id",)),
    Table("floodlight_tag", "structure", "A Floodlight conversion tag of an advertiser, with its attribution lookback window.", (
        _c("floodlight_tag_id", "INTEGER", "Tag ID."),
        _c("advertiser_id", "INTEGER", "Advertiser."),
        _c("tag_name", "VARCHAR", "Tag name."),
        _c("conversion_category", "VARCHAR", "Purchase, Lead, Sign-up, or Booking."),
        _c("lookback_window_days", "INTEGER", "Attribution lookback window: 30, 60, or 90 days."),
    ), ("floodlight_tag_id",)),
    # --- facts --------------------------------------------------------------
    Table("daily_stats", "fact", "Engine-reported performance of one campaign on one device on one day. Its conversions are the ENGINE AGGREGATE source: never add or join them with the conversion table or search_term_report.", (
        _c("report_date", "DATE", "Day."),
        _c("campaign_id", "INTEGER", "Campaign."),
        _c("device_id", "INTEGER", "Device."),
        _c("impressions", "INTEGER", "Impressions."),
        _c("clicks", "INTEGER", "Clicks."),
        _c("cost", "DOUBLE", "Spend in USD."),
        _c("conversions", "DOUBLE", "Engine-reported conversions (engine aggregate source)."),
        _c("conversion_value", "DOUBLE", "Engine-reported conversion value in USD."),
        _c("search_impression_share", "DOUBLE", "Share of eligible impressions won, 0 to 1; Search campaigns only.", nullable=True),
        _c("search_top_impression_share", "DOUBLE", "Share shown at the top of the page, 0 to 1; Search campaigns only. Weight by impressions when aggregating.", nullable=True),
        _c("search_lost_is_budget", "DOUBLE", "Impression share lost to budget, 0 to 1; Search campaigns only.", nullable=True),
        _c("search_lost_is_rank", "DOUBLE", "Impression share lost to ad rank, 0 to 1; Search campaigns only.", nullable=True),
    ), ("report_date", "campaign_id", "device_id")),
    Table("conversion", "fact", "One Floodlight conversion event (the FLOODLIGHT EVENT source), the subject of attribution. Never add these to daily_stats.conversions.", (
        _c("conversion_id", "INTEGER", "Conversion ID."),
        _c("floodlight_tag_id", "INTEGER", "Tag that fired."),
        _c("conversion_time", "TIMESTAMP", "When it happened."),
        _c("conversion_value", "DOUBLE", "Value in USD."),
        _c("device_id", "INTEGER", "Device of the converting session."),
    ), ("conversion_id",)),
    Table("attribution_path", "fact", "One touchpoint of a conversion's path (2 to 6 touches), with the credit each of six attribution models gives it; the credits of one model sum to 1 over a conversion's path. Channel value under a model = SUM(credit * conversion.conversion_value).", (
        _c("conversion_id", "INTEGER", "Conversion."),
        _c("touch_index", "INTEGER", "Position in the path, 1 = first touch."),
        _c("path_length", "INTEGER", "Number of touches in this path."),
        _c("channel_id", "INTEGER", "Channel of the touch."),
        _c("campaign_id", "INTEGER", "Paid search campaign of the touch; NULL for other channels.", nullable=True),
        _c("touch_time", "TIMESTAMP", "When the touch happened."),
        _c("last_click_credit", "DOUBLE", "Last-click credit: 1 on the last touch."),
        _c("first_click_credit", "DOUBLE", "First-click credit: 1 on the first touch."),
        _c("linear_credit", "DOUBLE", "Linear credit: 1 / path_length on every touch."),
        _c("time_decay_credit", "DOUBLE", "Time-decay credit: 7-day half-life before the conversion."),
        _c("position_credit", "DOUBLE", "Position-based credit: 40% first, 40% last, 20% spread over the middle (50/50 for 2 touches)."),
        _c("data_driven_credit", "DOUBLE", "Data-driven credit: a NON-PRODUCTION SIMULATION, illustrative only; always say so."),
    ), ("conversion_id", "touch_index")),
    Table("search_term_report", "fact", "Performance of one search term in one ad group on one day (the SEARCH TERM source of conversions). keyword_id is NULL for broad-match overflow terms that matched no keyword of the ad group.", (
        _c("report_date", "DATE", "Day."),
        _c("ad_group_id", "INTEGER", "Ad group."),
        _c("keyword_id", "INTEGER", "Keyword that matched; NULL for broad-match overflow.", nullable=True),
        _c("search_term", "VARCHAR", "What the user searched."),
        _c("match_type_id", "INTEGER", "Match type that served the ad."),
        _c("impressions", "INTEGER", "Impressions."),
        _c("clicks", "INTEGER", "Clicks."),
        _c("cost", "DOUBLE", "Spend in USD."),
        _c("conversions", "DOUBLE", "Conversions credited to the search term (search term source)."),
    ), ("report_date", "ad_group_id", "search_term")),
)
# fmt: on



#: Foreign keys, child column -> parent table and column. Declared in the DDL,
#: so schema reflection shows the agent how the tables join.
FOREIGN_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "agency": [("region_id", "region", "region_id")],
    "advertiser": [("industry_id", "industry", "industry_id"), ("region_id", "region", "region_id")],
    "agency_client": [("agency_id", "agency", "agency_id"), ("advertiser_id", "advertiser", "advertiser_id")],
    "engine_account": [("advertiser_id", "advertiser", "advertiser_id")],
    "bid_strategy": [("advertiser_id", "advertiser", "advertiser_id"), ("bid_strategy_type_id", "bid_strategy_type", "bid_strategy_type_id")],
    "campaign": [("engine_account_id", "engine_account", "engine_account_id"), ("bid_strategy_id", "bid_strategy", "bid_strategy_id")],
    "campaign_budget": [("campaign_id", "campaign", "campaign_id")],
    "ad_group": [("campaign_id", "campaign", "campaign_id")],
    "keyword": [("ad_group_id", "ad_group", "ad_group_id"), ("match_type_id", "match_type", "match_type_id")],
    "text_ad": [("ad_group_id", "ad_group", "ad_group_id")],
    "floodlight_tag": [("advertiser_id", "advertiser", "advertiser_id")],
    "daily_stats": [("campaign_id", "campaign", "campaign_id"), ("device_id", "device", "device_id")],
    "conversion": [("floodlight_tag_id", "floodlight_tag", "floodlight_tag_id"), ("device_id", "device", "device_id")],
    "attribution_path": [("conversion_id", "conversion", "conversion_id"), ("channel_id", "channel", "channel_id"), ("campaign_id", "campaign", "campaign_id")],
    "search_term_report": [("ad_group_id", "ad_group", "ad_group_id"), ("keyword_id", "keyword", "keyword_id"), ("match_type_id", "match_type", "match_type_id")],
}

#: Portable catalog types to DuckDB types.
DUCKDB_TYPES = {"INTEGER": "BIGINT", "DOUBLE": "DOUBLE", "VARCHAR": "VARCHAR", "DATE": "DATE", "TIMESTAMP": "TIMESTAMP", "BOOLEAN": "BOOLEAN"}

#: The six attribution models, by their credit column.
ATTRIBUTION_MODELS = {
    "last_click": "last_click_credit",
    "first_click": "first_click_credit",
    "linear": "linear_credit",
    "time_decay": "time_decay_credit",
    "position_based": "position_credit",
    "data_driven_simulated": "data_driven_credit",
}


# =============================================================================
# Data
# =============================================================================
#: The last day of daily_stats, and the anchor of every relative window.
REFERENCE_DATE = dt.date(2026, 7, 13)

#: The seed of the warehouse the agent is demoed and deployed on.
DEFAULT_SEED = 42

#: Days of daily_stats and search_term_report, ending on REFERENCE_DATE.
STATS_DAYS = 62

#: Days back conversions are spread over.
CONVERSION_DAYS = 90

#: Number of Floodlight conversion events.
N_CONVERSIONS = 5000

#: Path length N -> weight, from the historical attribution data.
PATH_LENGTH_WEIGHTS = {2: 40, 3: 30, 4: 15, 5: 10, 6: 5}

# fmt: off
INDUSTRIES = ["Retail", "Travel", "Financial Services", "Healthcare", "Auto", "Insurance", "B2B SaaS", "Education", "Real Estate", "Restaurants"]
#: Average order value and Google CPC by industry, in USD.
INDUSTRY_ECONOMICS = {
    "Retail": (85, 1.2), "Travel": (420, 1.6), "Financial Services": (310, 4.8), "Healthcare": (240, 3.1),
    "Auto": (520, 2.4), "Insurance": (380, 5.6), "B2B SaaS": (900, 6.2), "Education": (260, 3.4),
    "Real Estate": (650, 2.2), "Restaurants": (45, 0.9),
}
REGIONS = ["New England", "Middle Atlantic", "East North Central", "West North Central", "South Atlantic", "East South Central", "West South Central", "Mountain", "Pacific"]
BID_STRATEGY_TYPES = [("Manual CPC", False), ("Enhanced CPC", False), ("Maximize Clicks", True), ("Maximize Conversions", True), ("Target CPA", True), ("Target ROAS", True)]
MATCH_TYPES = ["Exact", "Phrase", "Broad"]
DEVICES = ["Mobile", "Desktop", "Tablet"]
CHANNELS = [("Paid Search", "lower"), ("Display", "upper"), ("Paid Social", "upper"), ("Email", "mid"), ("Organic Search", "mid"), ("Direct", "lower")]
AGENCY_TIERS = ["Platinum"] * 2 + ["Gold"] * 4 + ["Silver"] * 5 + ["Standard"] * 4
NAME_A = ["North", "Blue", "Summit", "Bright", "Cedar", "Harbor", "Prairie", "Silver", "Lake", "Iron", "Golden", "Maple", "Union", "Pioneer", "Crescent", "Atlas"]
NAME_B = ["Peak", "Line", "Works", "Labs", "Point", "Bridge", "Field", "Stone", "Path", "Wave", "Forge", "Grove", "Gate", "Ridge", "Crest", "Haven"]
TERM_WORDS = ["best", "cheap", "near me", "online", "reviews", "deals", "buy", "price", "free shipping", "2026", "top", "local", "quote", "compare", "discount"]

#: Device -> (share of impressions, CTR, conversion rate, CPC multiplier).
DEVICE_PROFILE = {"Mobile": (0.60, 0.034, 0.030, 0.95), "Desktop": (0.32, 0.046, 0.062, 1.10), "Tablet": (0.08, 0.030, 0.038, 0.90)}
#: Engine -> (CPC multiplier, conversion-rate multiplier).
ENGINE_PROFILE = {"Google Ads": (1.00, 1.00), "Microsoft Advertising": (0.80, 0.88)}
# fmt: on


def _daterange(end: dt.date, days: int) -> list[dt.date]:
    return [end - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _name(rng: random.Random, suffix: str) -> str:
    return f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {suffix}"


def _dimensions() -> dict[str, list[tuple]]:
    return {
        "industry": [(i + 1, name) for i, name in enumerate(INDUSTRIES)],
        "region": [(i + 1, name) for i, name in enumerate(REGIONS)],
        "bid_strategy_type": [
            (i + 1, n, s) for i, (n, s) in enumerate(BID_STRATEGY_TYPES)
        ],
        "match_type": [(i + 1, name) for i, name in enumerate(MATCH_TYPES)],
        "device": [(i + 1, name) for i, name in enumerate(DEVICES)],
        "channel": [(i + 1, n, f) for i, (n, f) in enumerate(CHANNELS)],
    }


def _organization(rng: random.Random) -> dict[str, list[tuple]]:
    agencies = []
    for i, tier in enumerate(AGENCY_TIERS, start=1):
        name = _name(rng, "Media")
        slug = name.lower().replace(" ", "")
        agencies.append(
            (
                i,
                name,
                tier,
                rng.randint(1, len(REGIONS)),
                rng.randint(1985, 2019),
                f"partnerships@{slug}.example.com",
                f"+1-312-555-{1000 + i:04d}",
            )
        )
    advertisers = []
    for i in range(1, 81):
        name = _name(rng, "Co")
        advertisers.append(
            (
                i,
                name,
                (i - 1) % len(INDUSTRIES) + 1,
                rng.randint(1, len(REGIONS)),
                f"https://www.{name.lower().replace(' ', '')}.example.com",
            )
        )
    managed = rng.sample(range(1, 81), 64)
    clients = []
    # higher tiers manage more advertisers
    tier_weights = {"Platinum": 6, "Gold": 4, "Silver": 2, "Standard": 1}
    agency_weights = [tier_weights[tier] for tier in AGENCY_TIERS]
    for advertiser_id in sorted(managed):
        agency_id = rng.choices(range(1, 16), weights=agency_weights)[0]
        start = REFERENCE_DATE - dt.timedelta(days=rng.randint(200, 1500))
        active = rng.random() > 0.09
        end = (
            None if active else REFERENCE_DATE - dt.timedelta(days=rng.randint(10, 150))
        )
        if rng.random() < 0.85:
            fee = ("percentage", round(rng.uniform(0.08, 0.20), 3), None)
        else:
            fee = ("flat", None, float(rng.randrange(60_000, 240_000, 5_000)))
        clients.append((agency_id, advertiser_id, start, end, *fee, 1 if active else 0))
    return {"agency": agencies, "advertiser": advertisers, "agency_client": clients}


def _structure(rng: random.Random, advertisers: list[tuple]) -> dict[str, list[tuple]]:
    accounts, strategies, campaigns, budgets = [], [], [], []
    ad_groups, keywords, ads, tags = [], [], [], []
    ids = {
        "acct": 0,
        "bs": 0,
        "camp": 0,
        "budget": 0,
        "ag": 0,
        "kw": 0,
        "ad": 0,
        "tag": 0,
    }

    def nid(key: str) -> int:
        ids[key] += 1
        return ids[key]

    for advertiser_id, adv_name, industry_id, _, _ in advertisers:
        industry = INDUSTRIES[industry_id - 1]
        aov, _cpc = INDUSTRY_ECONOMICS[industry]
        adv_strategies = []
        for type_id in rng.sample(range(1, 7), 3):
            bs_id = nid("bs")
            type_name = BID_STRATEGY_TYPES[type_id - 1][0]
            target_cpa = (
                round(aov * rng.uniform(0.06, 0.16), 2)
                if type_name == "Target CPA"
                else None
            )
            target_roas = (
                round(rng.uniform(2.5, 6.0), 2) if type_name == "Target ROAS" else None
            )
            strategies.append(
                (
                    bs_id,
                    advertiser_id,
                    type_id,
                    f"{adv_name} {type_name}",
                    target_cpa,
                    target_roas,
                )
            )
            adv_strategies.append(bs_id)
        for _ in range(5):
            tag_id = nid("tag")
            category = rng.choice(["Purchase", "Lead", "Sign-up", "Booking"])
            tags.append(
                (
                    tag_id,
                    advertiser_id,
                    f"{adv_name} {category} {tag_id}",
                    category,
                    rng.choice([30, 60, 90]),
                )
            )
        engines = ["Google Ads"] + (
            ["Microsoft Advertising"] if rng.random() < 0.75 else []
        )
        for engine in engines:
            acct_id = nid("acct")
            accounts.append((acct_id, advertiser_id, engine, f"{adv_name} - {engine}"))
            for c in range(8 if engine == "Google Ads" else 6):
                camp_id = nid("camp")
                ctype = rng.choices(
                    ["Search", "Shopping", "Display"], weights=[75, 15, 10]
                )[0]
                status = "Enabled" if rng.random() < 0.86 else "Paused"
                start = REFERENCE_DATE - dt.timedelta(days=rng.randint(70, 700))
                campaigns.append(
                    (
                        camp_id,
                        acct_id,
                        rng.choice(adv_strategies),
                        f"{adv_name} {ctype} {c + 1:02d}",
                        ctype,
                        status,
                        start,
                    )
                )
                base = round(
                    rng.uniform(80, 1500) * (1.6 if ctype == "Search" else 0.8), 2
                )
                versions = rng.choices([1, 2, 3], weights=[35, 45, 20])[0]
                version_dates = sorted(
                    {start}
                    | {
                        REFERENCE_DATE
                        - dt.timedelta(days=rng.randint(1, STATS_DAYS - 1))
                        for _ in range(versions - 1)
                    }
                )
                for v_date in version_dates:
                    budgets.append(
                        (
                            nid("budget"),
                            camp_id,
                            round(base * rng.uniform(0.7, 1.3), 2),
                            v_date,
                        )
                    )
                for g in range(rng.randint(3, 6)):
                    ag_id = nid("ag")
                    ad_groups.append(
                        (
                            ag_id,
                            camp_id,
                            f"Ad Group {g + 1}",
                            "Enabled" if rng.random() < 0.9 else "Paused",
                        )
                    )
                    for a in range(rng.randint(3, 5)):
                        ads.append(
                            (
                                nid("ad"),
                                ag_id,
                                f"{adv_name} {rng.choice(TERM_WORDS).title()}",
                                f"Shop {industry.lower()} offers {a + 1}",
                                "Enabled" if rng.random() < 0.92 else "Paused",
                            )
                        )
                    if ctype == "Display":
                        continue
                    for k in range(rng.randint(5, 11)):
                        quality = max(1, min(10, int(rng.gauss(6.4, 2.0))))
                        keywords.append(
                            (
                                nid("kw"),
                                ag_id,
                                f"{industry.lower()} {rng.choice(TERM_WORDS)} {k + 1}",
                                rng.choices([1, 2, 3], weights=[40, 35, 25])[0],
                                round(_cpc * rng.uniform(0.6, 1.8), 2),
                                quality,
                                "Enabled" if rng.random() < 0.9 else "Paused",
                            )
                        )
    return {
        "engine_account": accounts,
        "bid_strategy": strategies,
        "campaign": campaigns,
        "campaign_budget": budgets,
        "ad_group": ad_groups,
        "keyword": keywords,
        "text_ad": ads,
        "floodlight_tag": tags,
    }


def _budget_on(versions: list[tuple[dt.date, float]], day: dt.date) -> float:
    """
    The daily budget in effect on ``day``: the latest version starting on or
    before it (the pattern the agent must use instead of a plain join).
    """
    budget = versions[0][1]
    for effective, amount in versions:
        if effective <= day:
            budget = amount
    return budget


def _daily_stats(rng: random.Random, tables: dict[str, list[tuple]]) -> list[tuple]:
    accounts = {row[0]: row for row in tables["engine_account"]}
    advertisers = {row[0]: row for row in tables["advertiser"]}
    versions: dict[int, list[tuple[dt.date, float]]] = {}
    for _, camp_id, amount, effective in tables["campaign_budget"]:
        versions.setdefault(camp_id, []).append((effective, amount))
    days = _daterange(REFERENCE_DATE, STATS_DAYS)
    rows = []
    for camp_id, acct_id, _, _, ctype, status, start in tables["campaign"]:
        if status != "Enabled":
            continue
        engine = accounts[acct_id][2]
        industry = INDUSTRIES[advertisers[accounts[acct_id][1]][2] - 1]
        aov, cpc_base = INDUSTRY_ECONOMICS[industry]
        cpc_mult, cr_mult = ENGINE_PROFILE[engine]
        constrained = ctype == "Search" and rng.random() < 0.3
        quality = rng.uniform(0.75, 1.25)
        for day in days:
            if day < start:
                continue
            budget = _budget_on(sorted(versions[camp_id]), day)
            pacing = rng.uniform(0.93, 1.18) if constrained else rng.uniform(0.35, 0.85)
            spend = budget * pacing * (0.85 if day.weekday() >= 5 else 1.0)
            lost_budget = (
                rng.uniform(0.18, 0.5) if constrained else rng.uniform(0.0, 0.05)
            )
            lost_rank = rng.uniform(0.05, 0.35)
            # impressions are split by device share first, so Mobile gets ~60%
            # of them whatever its CPC; spend follows from clicks and CPC
            cost_per_impression = sum(
                share * ctr * cpc_base * cpc_mult * dev_cpc
                for share, ctr, _, dev_cpc in DEVICE_PROFILE.values()
            )
            total_impressions = spend / cost_per_impression
            for device_id, device in enumerate(DEVICES, start=1):
                share, ctr, cr, dev_cpc = DEVICE_PROFILE[device]
                cpc = cpc_base * cpc_mult * dev_cpc * rng.uniform(0.9, 1.1)
                impressions = max(
                    1, int(total_impressions * share * rng.uniform(0.95, 1.05))
                )
                clicks = max(0, int(impressions * ctr * rng.uniform(0.85, 1.15)))
                cost = round(clicks * cpc, 2)
                conversions = round(
                    clicks * cr * cr_mult * quality * rng.uniform(0.7, 1.3), 2
                )
                value = round(conversions * aov * rng.uniform(0.85, 1.15), 2)
                if ctype == "Search":
                    is_share = round(max(0.05, 1 - lost_budget - lost_rank), 4)
                    top_share = round(is_share * rng.uniform(0.45, 0.8), 4)
                    shares = (
                        is_share,
                        top_share,
                        round(lost_budget, 4),
                        round(lost_rank, 4),
                    )
                else:
                    shares = (None, None, None, None)
                rows.append(
                    (
                        day,
                        camp_id,
                        device_id,
                        impressions,
                        clicks,
                        cost,
                        conversions,
                        value,
                        *shares,
                    )
                )
    return rows


def _attribution(
    rng: random.Random, tables: dict[str, list[tuple]]
) -> tuple[list[tuple], list[tuple]]:
    tags = tables["floodlight_tag"]
    advertisers = {row[0]: row for row in tables["advertiser"]}
    search_campaigns: dict[int, list[int]] = {}
    accounts = {row[0]: row for row in tables["engine_account"]}
    for camp_id, acct_id, _, _, ctype, _, _ in tables["campaign"]:
        if ctype == "Search":
            search_campaigns.setdefault(accounts[acct_id][1], []).append(camp_id)
    channel_ids = {name: i + 1 for i, (name, _) in enumerate(CHANNELS)}
    first_weights = {
        "Paid Search": 22,
        "Display": 30,
        "Paid Social": 26,
        "Email": 6,
        "Organic Search": 12,
        "Direct": 4,
    }
    middle_weights = {
        "Paid Search": 25,
        "Display": 18,
        "Paid Social": 18,
        "Email": 17,
        "Organic Search": 17,
        "Direct": 5,
    }
    last_weights = {
        "Paid Search": 64,
        "Display": 3,
        "Paid Social": 5,
        "Email": 9,
        "Organic Search": 11,
        "Direct": 8,
    }
    end = dt.datetime.combine(REFERENCE_DATE, dt.time(23, 59, 59))
    lengths, weights = zip(*PATH_LENGTH_WEIGHTS.items())
    conversions, paths = [], []
    for conversion_id in range(1, N_CONVERSIONS + 1):
        tag_id, advertiser_id, _, _, lookback = rng.choice(tags)
        aov, _ = INDUSTRY_ECONOMICS[INDUSTRIES[advertisers[advertiser_id][2] - 1]]
        when = end - dt.timedelta(seconds=rng.randint(0, CONVERSION_DAYS * 86400 - 1))
        value = round(aov * rng.lognormvariate(0, 0.45), 2)
        device_id = rng.choices([1, 2, 3], weights=[55, 37, 8])[0]
        conversions.append((conversion_id, tag_id, when, value, device_id))
        n = rng.choices(lengths, weights=weights)[0]
        # first touch at most the tag's lookback window (<= 90 days) before the
        # conversion, last touch shortly before it, the others in between
        span_hours = min(lookback * 24, rng.expovariate(1 / 120) + 2)
        first = when - dt.timedelta(hours=span_hours)
        last = when - dt.timedelta(minutes=rng.randint(1, 90))
        middle = sorted(first + (last - first) * rng.random() for _ in range(n - 2))
        times = [first, *middle, last]
        names = [
            rng.choices(list(first_weights), weights=list(first_weights.values()))[0]
        ]
        names += [
            rng.choices(list(middle_weights), weights=list(middle_weights.values()))[0]
            for _ in range(n - 2)
        ]
        names += [
            rng.choices(list(last_weights), weights=list(last_weights.values()))[0]
        ]
        decay = [2 ** (-((when - t).total_seconds() / 86400) / 7) for t in times]
        decay_sum = sum(decay)
        if n == 2:
            position = [0.5, 0.5]
        else:
            position = [0.4] + [0.2 / (n - 2)] * (n - 2) + [0.4]
        upper = [
            1.6 if CHANNELS[channel_ids[name] - 1][1] == "upper" else 1.0
            for name in names
        ]
        noise = [u * rng.uniform(0.7, 1.3) for u in upper]
        noise_sum = sum(noise)
        for i in range(n):
            linear = 1 / n
            dda = 0.45 * linear + 0.25 * position[i] + 0.30 * noise[i] / noise_sum
            campaign_id = (
                rng.choice(search_campaigns[advertiser_id])
                if names[i] == "Paid Search" and advertiser_id in search_campaigns
                else None
            )
            paths.append(
                (
                    conversion_id,
                    i + 1,
                    n,
                    channel_ids[names[i]],
                    campaign_id,
                    times[i].replace(microsecond=0),
                    1.0 if i == n - 1 else 0.0,
                    1.0 if i == 0 else 0.0,
                    round(linear, 6),
                    round(decay[i] / decay_sum, 6),
                    round(position[i], 6),
                    round(dda, 6),
                )
            )
    return conversions, paths


def _search_terms(rng: random.Random, tables: dict[str, list[tuple]]) -> list[tuple]:
    campaigns = {row[0]: row for row in tables["campaign"]}
    keywords: dict[int, list[tuple]] = {}
    for kw in tables["keyword"]:
        keywords.setdefault(kw[1], []).append(kw)
    days = _daterange(REFERENCE_DATE, STATS_DAYS)
    rows = []
    for ag_id, camp_id, _, status in tables["ad_group"]:
        camp = campaigns[camp_id]
        if (
            camp[4] != "Search"
            or camp[5] != "Enabled"
            or status != "Enabled"
            or ag_id not in keywords
        ):
            continue
        ag_keywords = keywords[ag_id]
        for day in days:
            if rng.random() < 0.08:
                continue
            seen = set()
            for _ in range(rng.choices([1, 2, 3, 4], weights=[30, 35, 25, 10])[0]):
                if rng.random() < 0.12:
                    keyword_id, match_type_id = None, 3
                    term = f"{rng.choice(TERM_WORDS)} {rng.choice(NAME_B).lower()} {rng.choice(TERM_WORDS)}"
                else:
                    kw = rng.choice(ag_keywords)
                    keyword_id, match_type_id = kw[0], kw[3]
                    term = (
                        kw[2]
                        if match_type_id == 1
                        else f"{kw[2]} {rng.choice(TERM_WORDS)}"
                    )
                if term in seen:
                    continue
                seen.add(term)
                impressions = rng.randint(1, 160)
                clicks = int(impressions * rng.uniform(0.0, 0.09))
                cost = round(clicks * rng.uniform(0.4, 4.5), 2)
                conversions = (
                    round(clicks * rng.uniform(0.0, 0.08), 2)
                    if keyword_id
                    else round(clicks * rng.uniform(0.0, 0.02), 2)
                )
                rows.append(
                    (
                        day,
                        ag_id,
                        keyword_id,
                        term,
                        match_type_id,
                        impressions,
                        clicks,
                        cost,
                        conversions,
                    )
                )
    return rows


def generate(seed: int = DEFAULT_SEED) -> dict[str, list[tuple]]:
    """
    Every table of the warehouse for ``seed``, as rows in catalog column
    order, by table name. The same seed always gives the same rows.
    """
    rng = random.Random(seed)
    tables = _dimensions()
    tables.update(_organization(rng))
    tables.update(_structure(rng, tables["advertiser"]))
    tables["daily_stats"] = _daily_stats(rng, tables)
    tables["conversion"], tables["attribution_path"] = _attribution(rng, tables)
    tables["search_term_report"] = _search_terms(rng, tables)
    return tables


def count_rows(tables: dict[str, list[tuple]]) -> int:
    """
    The total number of rows over every table.
    """
    return sum(len(rows) for rows in tables.values())


# =============================================================================
# DuckDB
# =============================================================================
def render_create_table(table: Table) -> str:
    """
    ``CREATE TABLE`` of one table, with its primary and foreign keys.
    """
    lines = []
    for column in table.columns:
        null = "" if column.nullable else " NOT NULL"
        lines.append(f"    {column.name} {DUCKDB_TYPES[column.type]}{null}")
    lines.append(f"    PRIMARY KEY ({', '.join(table.primary_key)})")
    for column, parent, parent_column in FOREIGN_KEYS.get(table.name, []):
        lines.append(f"    FOREIGN KEY ({column}) REFERENCES {SCHEMA_NAME}.{parent}({parent_column})")
    return f"CREATE TABLE {SCHEMA_NAME}.{table.name} (\n" + ",\n".join(lines) + "\n)"


def render_views() -> list[str]:
    """
    The two helper views: the reference date every window ends on, and the
    channel value under each of the six attribution models.
    """
    selects = [
        f"SELECT '{model}' AS attribution_model, ch.channel_name, "
        f"SUM(ap.{column} * c.conversion_value) AS attributed_value, "
        f"SUM(ap.{column}) AS attributed_conversions "
        f"FROM {SCHEMA_NAME}.attribution_path ap "
        f"JOIN {SCHEMA_NAME}.conversion c ON c.conversion_id = ap.conversion_id "
        f"JOIN {SCHEMA_NAME}.channel ch ON ch.channel_id = ap.channel_id "
        f"GROUP BY ch.channel_name"
        for model, column in ATTRIBUTION_MODELS.items()
    ]
    return [
        f"CREATE VIEW {SCHEMA_NAME}.v_reference_date AS SELECT MAX(report_date) AS reference_date FROM {SCHEMA_NAME}.daily_stats",
        f"CREATE VIEW {SCHEMA_NAME}.mv_attribution_six_models AS " + " UNION ALL ".join(selects),
    ]


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def build_duckdb(path: Path, seed: int = DEFAULT_SEED) -> int:
    """
    Generate the warehouse of ``seed`` into a new DuckDB file at ``path``
    (replaced if it exists), loading each table through CSV and ``COPY`` in
    foreign key order. Returns the number of rows.
    """
    import duckdb

    tables = generate(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(f"CREATE SCHEMA {SCHEMA_NAME}")
        with tempfile.TemporaryDirectory() as dir_tmp:
            for table in TABLES:
                connection.execute(render_create_table(table))
                path_csv = Path(dir_tmp) / f"{table.name}.csv"
                with path_csv.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(table.column_names)
                    for row in tables[table.name]:
                        writer.writerow([_csv_value(value) for value in row])
                connection.execute(f"COPY {SCHEMA_NAME}.{table.name} FROM '{path_csv}' (HEADER, NULLSTR '')")
        for statement in render_views():
            connection.execute(statement)
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    return count_rows(tables)


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Lumina Reach paid search warehouse (DuckDB).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parsed = parser.parse_args(args)
    n_rows = build_duckdb(parsed.out, parsed.seed)
    print(f"Built {parsed.out} (seed {parsed.seed}, {n_rows:,} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
