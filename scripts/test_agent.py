# -*- coding: utf-8 -*-

"""
Test script for the BI Agent.

Usage:
    .venv/bin/python scripts/test_agent.py

Change the `request` variable at the bottom to test different queries.
"""

from agent_app.one.api import one

# =============================================================================
# Test Requests - Onboarding & System Understanding (1-3)
# =============================================================================

# Understanding system capabilities
request_01 = """
What can you help me with? What are your main capabilities?
""".strip()

# Understanding database entities and relationships
request_02 = """
Can you explain the main entities in this database and how they relate to each other?
""".strip()

# Understanding the account structure
request_03 = """
How is a paid search account organized, from advertiser down to keyword? How many of each level does the portfolio have?
""".strip()

# =============================================================================
# Test Requests - Simple Queries (4-6)
# =============================================================================

# Simple count query
request_04 = """
How many campaigns do we have? Break it down by campaign type and status.
""".strip()

# Simple filter query
request_05 = """
List the enabled keywords with a quality score of 2 or lower. Include the keyword text, match type, and max CPC.
""".strip()

# Simple date filter query
request_06 = """
What was total spend, clicks and conversions over the last 7 days?
""".strip()

# =============================================================================
# Test Requests - Medium Complexity (7-8)
# =============================================================================

# Join with a ratio of sums
request_07 = """
Compare Google Ads and Microsoft Advertising over the last 30 days on CPC, conversion rate and CPA.
""".strip()

# Versioned budgets: must join the budget in effect, not every version
request_08 = """
Which campaigns spent the most relative to their daily budget over the last 7 days?
""".strip()

# =============================================================================
# Test Requests - Complex Multi-Step Queries (9-10)
# =============================================================================

# Attribution across six models
request_09 = """
For each channel, how much conversion value does it earn under each of the six attribution models? Which channels does last-click under-credit the most?
""".strip()

# A conversion-source trap: the agent must refuse to add the sources together
request_10 = """
What is the total number of conversions if you add the engine-reported conversions and the Floodlight conversions together for the last 30 days?
""".strip()

# =============================================================================
# Run the selected request
# =============================================================================

# Change this to test different requests (request_01 to request_10)
request = request_01
# request = request_02
# request = request_03
# request = request_04
# request = request_05
# request = request_06
# request = request_07
# request = request_08
# request = request_09
# request = request_10

one.agent(request)
