<!--
The long-form explainer behind the home page's one-paragraph pitch.

Opened from the home page and dismissed again without navigating. It exists
because a headline and one paragraph cannot carry a whole business domain, and
a reader who does not already know the industry will otherwise not understand
what any of the agent's answers are for.

It describes the **app**, not the dataset. What ships outward looks like a
dataset with an agent attached, but what a reader actually needs is what the
app is for: whose problem it solves, on what evidence, and how far it goes
today. The first three sections explain the world, the last three explain what
the agent does in it.

Written for a stranger with no domain knowledge and no context about who built
this: the industry, not an employer; the problem, not a project. Common sense
should be enough to follow every sentence.

The title and subtitle above it live in `site.toml` under
`[home.businessContext]`, because they label the control that opens this.

At most one mermaid diagram in the whole file, under ten nodes.
-->

## How a paid search agency network makes money

An agency network runs search advertising on behalf of brands. Each member agency manages a group of advertisers' accounts on Google Ads and Microsoft Advertising: it picks the keywords, writes the ads, sets the budgets and watches the results. The network is paid a fee on the spend it manages, usually 8% to 20%, with a few clients paying a flat yearly amount instead.

So revenue has two drivers. One is how much spend the network manages, here about $20 million a month across 80 brands. The other is how well it manages that spend, because a brand whose cost per sale keeps falling renews and grows, and a brand whose cost per sale drifts up eventually leaves. The largest cost is the people who answer the brands' questions: analysts writing one report after another by hand.

## Where the money quietly leaks

None of these problems show up in the monthly total. That is why they persist.

- **The wrong channel gets the credit.** A typical customer sees a display ad, then a social post, then searches for the brand and buys. The standard report gives the whole sale to that last search. Display and social look worthless and get cut, and sales fall a quarter later for a reason nobody connects back. The report never looks wrong, because it is internally consistent. It just answers a narrower question than the one being asked.
- **Budgets bind where they should not, and not where they should.** A campaign that runs out of money by mid-afternoon misses every auction after that, even when each sale it wins is profitable. Another overspends on one that is not. Daily budgets change over time, so comparing spend with "the budget" without asking which version was in force gives a confident wrong answer.
- **Automated bidding is trusted rather than checked.** Brands increasingly let the engine set every bid toward a target cost per sale. When it misses the target, it misses quietly, spread across hundreds of campaigns. Nobody sees it unless someone audits target against actual, campaign by campaign.
- **Small waste adds up.** Keywords that collect clicks and never convert, and loosely matched searches nobody chose to bid on, each cost a little. Spread thin across thousands of keywords, they never stand out, which is exactly why they are never cleaned up.
- **"Conversions" is three different numbers.** The engines count sales their own way, the site tags count them another way, and the search term report a third. Add two of them together and the total looks plausible and is simply wrong.

## What that looks like in the data

These leaks can only be seen together, because each one hides behind another. An attribution question needs the conversion paths. A budget question needs the daily spend and every version of the budget. A waste question needs the individual search terms behind the campaign totals. One table at a time, every answer looks fine.

The warehouse behind this agent holds the whole picture for the network: 15 agencies and 80 advertisers in 10 industries; their 144 engine accounts, 1,024 campaigns, 4,621 ad groups and 33,399 keywords; 62 days of daily performance by campaign and device; 62 days of search terms; and 5,000 tracked conversions, each with the 2 to 6 touchpoints that led to it, credited under six attribution models. All of it is anchored to a fixed reference date, 13 July 2026, so "the last 30 days" means the same thing every time it is asked.

## What the agent does with it

You ask in plain English. The agent reads the database structure, works out which tables have to be joined and at what grain, writes the query, runs it, and then explains what came back in business terms rather than handing you a grid of numbers.

Before any query runs, it is checked. A query that would mix the three kinds of conversions, average a ratio, invent a column or touch contact details is refused with the reason, and the agent rewrites it. The data itself is read-only.

It picks its format to match the question. Exact values arrive as a table. When the shape of the numbers is the point, such as a ranking across channels, a trend across days, or a gap between two attribution models, it draws a chart. When the answer is about how something flows rather than how much, it draws a diagram.

```mermaid
flowchart LR
    Q[Your question] --> S[Reads the schema]
    S --> W[Writes SQL]
    W --> G{Guardrails}
    G -- refused, with the reason --> W
    G -- passed --> R[Runs it read-only]
    R --> A[Explains the answer]
```

Every number it reports comes from a query it actually ran against the data, not from its own recollection. If you want to check it, ask it to show you the SQL and the reasoning; it keeps both.

## What you can ask, and how to read the answers

Almost every useful question falls into one of four groups. You do not need to phrase them precisely or know any table names.

- **Attribution.** How much each channel is worth under last-click, first-click, linear, time-decay, position-based and a simulated data-driven model; which channels open journeys and which close them; how long journeys take.
- **Budget efficiency.** Which campaigns overspend the budget in force, which automated-bidding campaigns miss their target, which profitable campaigns are held back only by budget, and how cost per sale moves day by day.
- **Engines and devices.** Google against Microsoft, and phone against desktop against tablet, on cost per click, conversion rate, cost per sale and return on spend.
- **Waste.** Keywords and search terms that spent without converting, low-quality keywords in high-spend campaigns, and spend on searches no keyword was chosen for.

You can also ask about the portfolio itself: industries, agency tiers, the largest advertisers and who manages them.

Two habits make the answers far more useful. First, ratios hide the finding when they are averaged: the average of each campaign's cost per sale is not the network's cost per sale, and an average impression share ignores how many impressions each share was won on. The agent always divides totals by totals; ask for the breakdown rather than the mean.

Second, say which conversions you mean if it matters. The agent names the source it used in every answer about conversions, and it will not add two sources together, because the result would be a number that measures nothing.

## Beyond read-only

This app only reads. It can query anything in the record and explain it, but it cannot change a single row. That is a deliberate choice for something anyone can open, not a limitation of what the approach can do.

The same architecture supports the other half. An agent can be given tools that act rather than only report: pause a keyword that has spent without converting, propose a budget increase for a campaign held back by budget, open a review on an automated-bidding strategy that keeps missing its target. The analysis and the action then live in one place, instead of ending in a slide deck that someone has to act on by hand a week later.

That step is only responsible with two things attached. Guardrails: an agent gets narrowly scoped permissions, and the consequential actions need human approval rather than a broad key and good intentions. An auditable trail: every action it takes is attributable, reviewable, and reversible after the fact. An agent that can act without both is not a more capable product, it is an unaccountable one. That is why what you are looking at here stops at read-only.
