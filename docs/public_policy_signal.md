Yes. We can plan this as a real project.

The mission is  **not** :

```text
Copy congressional trades after disclosure.
```

The mission is:

```text
Build a public-information policy-alpha model that predicts which companies are entering the same opportunity zone congressional traders appear to exploit.
```

That means we reverse-engineer the  **conditions before the trade** , not the disclosure after the trade.

Your uploaded research already gives us the guardrails: most short-term strategies fail after costs, high-turnover strategies above about **50% monthly turnover** rarely survive, and any new factor needs serious statistical validation rather than “looked good once” energy.

---

# Project name

I’d call it:

```text
Kairos Policy Alpha
```

Core goal:

```text
Predict 30/60/90-day stock outperformance versus SPY using public policy, lobbying, federal spending, congressional relationship, and market data.
```

Primary target:

```text
60-day forward excess return versus SPY
```

Secondary targets:

```text
30-day excess return
90-day excess return
future congressional buy probability
```

---

# The whole system in one picture

```text
public data sources
   ↓
entity normalization
   ↓
ticker/company/member/bill/committee graph
   ↓
daily feature table
   ↓
Model A: congressional-buy probability
   ↓
Model B: 30/60/90-day excess-return ranker
   ↓
portfolio construction
   ↓
turnover/cost/risk gates
   ↓
SPY comparison
   ↓
promotion / reject report
```

The key is that every row must answer:

```text
As of this date, using only public data available by this date,
would this stock be a good 30/60/90-day candidate?
```

No leakage. No crystal-ball nonsense. No backtest goblin.

---

# Phase 0 — Define the research contract

Before code, we define what counts as success.

## Universe

Start with:

```text
S&P 500 + top liquid mid/large-cap U.S. stocks
```

Minimum constraints:

```yaml
universe:
  min_market_cap: 5_000_000_000
  preferred_market_cap: 10_000_000_000
  min_avg_dollar_volume_20d: 50_000_000
  min_price: 5.00
  exclude_otc: true
  exclude_etfs: true
  exclude_recent_ipos_days: 252
```

Why this matters: your source says large-cap/liquid constraints are critical for short-horizon strategies after costs.

## Benchmark

Use:

```text
SPY total return
```

Eventually also compare to:

```text
QQQ
Equal-weight S&P 500
Sector ETFs
Congress-tracking ETFs like NANC/KRUZ
```

But first benchmark is SPY.

## Horizons

```yaml
targets:
  primary: 60_trading_day_excess_return_vs_SPY
  secondary:
    - 30_trading_day_excess_return_vs_SPY
    - 90_trading_day_excess_return_vs_SPY
    - future_congressional_buy_60d
```

## Promotion rules

A strategy/model only gets promoted if:

```yaml
promotion:
  net_return_beats_SPY: true
  positive_out_of_sample_excess_return: true
  monthly_turnover_below: 0.50
  square_root_impact_costs: required
  no_random_time_splits: true
  walk_forward_validation: required
  no_single_sector_dependency: true
  no_single_year_dependency: true
```

---

# Phase 1 — Data sources

We need six data families.

## 1. Congressional trading data

We need:

```text
member
chamber
ticker/company/asset name
transaction type
transaction date
filing/disclosure date
amount range
owner: self/spouse/dependent/etc.
filing URL/source
```

Official House disclosures are provided through the House Clerk’s financial disclosure portal; the House Clerk site states it provides online public access to financial disclosure reports under the STOCK Act. ([House Disclosures](https://disclosures-clerk.house.gov/FinancialDisclosure?utm_source=chatgpt.com "Financial Disclosure Reports"))

The Senate side is trickier because filings are not as cleanly API-friendly, so we may either parse official sources or use a normalized provider. Third-party APIs exist, including Finnhub’s congressional trading endpoint and FMP’s House/Senate trading APIs, but those should be treated as convenience layers over public disclosures, not ground truth unless we audit them. ([Finnhub](https://finnhub.io/docs/api/congressional-trading?utm_source=chatgpt.com "Congressional Stock Trades API."))

Atomic table:

```sql
congress_trades (
    trade_id TEXT PRIMARY KEY,
    member_id TEXT,
    chamber TEXT,
    ticker TEXT,
    company_name TEXT,
    asset_description TEXT,
    transaction_type TEXT, -- buy/sell/exchange
    transaction_date DATE,
    disclosure_date DATE,
    amount_min NUMERIC,
    amount_max NUMERIC,
    amount_mid NUMERIC,
    owner_type TEXT,
    source_url TEXT,
    source_provider TEXT,
    created_at TIMESTAMP
)
```

Important no-leakage rule:

```text
The model cannot see a congressional trade until disclosure_date, not transaction_date.
```

But for reverse-engineering, we can study what public conditions existed before `transaction_date`.

So we use congressional trades two different ways:

```text
training label study:
features before transaction_date → did a trade happen?

live/predictive model:
features available today → expected return/congress-buy probability
```

---

## 2. Congress.gov bill and legislative data

Congress.gov has an official API with bill endpoints, latest action, Congressional Record data, communications, nominations, and other legislative collections. The Library of Congress states the Congress.gov API is available as version 3 and requires an API key. ([Congress.gov API](https://api.congress.gov/?utm_source=chatgpt.com "Congress.gov API"))

We need:

```text
bill_id
title
summary
sponsors
cosponsors
committees
latest action
action dates
subjects
policy areas
bill text
related bills
```

Tables:

```sql
bills (
    bill_id TEXT PRIMARY KEY,
    congress INTEGER,
    bill_type TEXT,
    bill_number TEXT,
    title TEXT,
    introduced_date DATE,
    latest_action_date DATE,
    latest_action_text TEXT,
    policy_area TEXT,
    summary TEXT,
    source_url TEXT
)

bill_actions (
    action_id TEXT PRIMARY KEY,
    bill_id TEXT,
    action_date DATE,
    action_text TEXT,
    action_type TEXT
)

bill_sponsors (
    bill_id TEXT,
    member_id TEXT,
    sponsor_type TEXT -- sponsor/cosponsor
)

bill_committees (
    bill_id TEXT,
    committee_id TEXT
)
```

Feature idea:

```text
If a bill relevant to semiconductors moves forward, semiconductor names get policy activity score.
```

---

## 3. Committees and member assignments

We need:

```text
member
committee
subcommittee
leadership/ranking role
date assignment starts/ends
committee jurisdiction
```

Tables:

```sql
members (
    member_id TEXT PRIMARY KEY,
    full_name TEXT,
    party TEXT,
    state TEXT,
    chamber TEXT,
    district TEXT,
    start_date DATE,
    end_date DATE
)

committees (
    committee_id TEXT PRIMARY KEY,
    chamber TEXT,
    name TEXT,
    jurisdiction_text TEXT
)

member_committee_assignments (
    member_id TEXT,
    committee_id TEXT,
    role TEXT,
    start_date DATE,
    end_date DATE
)
```

Feature examples:

```text
committee_company_overlap_score
committee_sector_overlap_score
committee_power_score
member_relevance_to_company
```

---

## 4. Lobbying and campaign finance data

For campaign finance, the FEC OpenFEC API is official and supports searches over FEC campaign-finance data; its documentation says data is updated nightly and bulk downloads are available. ([OpenFEC API](https://api.open.fec.gov/developers/?utm_source=chatgpt.com "OpenFEC API Documentation"))

For lobbying, OpenSecrets tracks campaign finance and lobbying data; its broader data ecosystem is useful, though access level/API details may vary by product and account. ([Wikipedia](https://en.wikipedia.org/wiki/OpenSecrets?utm_source=chatgpt.com "OpenSecrets"))

We need:

```text
company/industry lobbying spend
specific bills lobbied
lobbying clients
lobbying firms
PAC contributions
member/candidate contributions
industry contributions
quarterly changes
```

Tables:

```sql
lobbying_reports (
    report_id TEXT PRIMARY KEY,
    client_name TEXT,
    ticker TEXT,
    industry TEXT,
    period_start DATE,
    period_end DATE,
    amount NUMERIC,
    issues TEXT,
    specific_bills TEXT,
    lobbyist_names TEXT,
    source_url TEXT
)

campaign_contributions (
    contribution_id TEXT PRIMARY KEY,
    donor_name TEXT,
    donor_employer TEXT,
    donor_industry TEXT,
    recipient_member_id TEXT,
    recipient_committee TEXT,
    amount NUMERIC,
    contribution_date DATE,
    source_url TEXT
)
```

Feature examples:

```text
lobbying_spend_90d
lobbying_spend_yoy_change
bill_specific_lobbying_count
industry_pac_flow_to_relevant_committee_members
company_pac_flow_to_member
```

---

## 5. Federal contracts and grants

USAspending is the official open source for federal spending data, including contracts, grants, loans, and other awards; it also has a public API for comprehensive U.S. government spending data. ([USAspending](https://www.usaspending.gov/?utm_source=chatgpt.com "USAspending: Government Spending Open Data"))

We need:

```text
recipient company
award date
award amount
agency
sub-agency
NAICS/PSC
contract/grant/loan
place of performance
period of performance
```

Tables:

```sql
federal_awards (
    award_id TEXT PRIMARY KEY,
    recipient_name TEXT,
    ticker TEXT,
    award_date DATE,
    amount NUMERIC,
    agency TEXT,
    sub_agency TEXT,
    award_type TEXT,
    naics_code TEXT,
    psc_code TEXT,
    period_start DATE,
    period_end DATE,
    source_url TEXT
)
```

Feature examples:

```text
contract_awards_30d
contract_awards_90d
contract_awards_yoy_change
agency_exposure_score
defense_contract_momentum
broadband_grant_exposure
```

---

## 6. Market data

We already have Sharadar-style market history in your Kairos context. For this project we need:

```text
OHLCV
adjusted prices
market cap
sector/industry
shares outstanding
fundamentals
earnings dates
SPY/sector ETF returns
```

Tables:

```sql
prices_daily (
    ticker TEXT,
    date DATE,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    adj_close NUMERIC,
    volume NUMERIC,
    dollar_volume NUMERIC,
    PRIMARY KEY (ticker, date)
)

company_master (
    ticker TEXT PRIMARY KEY,
    company_name TEXT,
    cik TEXT,
    sector TEXT,
    industry TEXT,
    sic TEXT,
    naics TEXT,
    market_cap NUMERIC
)
```

---

# Phase 2 — Entity resolution

This is the ugly part. Also where half the project’s accuracy lives.

We need to map:

```text
Lockheed Martin Corp
LOCKHEED MARTIN CORPORATION
LMT
CIK 0000936468
federal award recipient names
lobbying client names
congressional asset descriptions
```

to one canonical company.

Canonical company table:

```sql
entities_company (
    company_id TEXT PRIMARY KEY,
    ticker TEXT,
    cik TEXT,
    canonical_name TEXT,
    sector TEXT,
    industry TEXT,
    naics TEXT,
    sic TEXT,
    active_start DATE,
    active_end DATE
)
```

Alias table:

```sql
company_aliases (
    alias TEXT,
    company_id TEXT,
    source TEXT,
    confidence NUMERIC,
    manually_verified BOOLEAN
)
```

Matching process:

```text
1. Exact ticker match
2. CIK match
3. Exact normalized name match
4. Fuzzy company-name match
5. Manual review queue for uncertain matches
```

Manual review table:

```sql
entity_resolution_review (
    source_record_id TEXT,
    source_name TEXT,
    suggested_company_id TEXT,
    suggested_ticker TEXT,
    confidence NUMERIC,
    status TEXT, -- pending/approved/rejected
    notes TEXT
)
```

Do not skip this. Bad entity resolution will make the model hallucinate relationships like a conspiracy board made of spaghetti.

---

# Phase 3 — Build the policy graph

At first, this can be relational tables. Later, graph ML.

## Nodes

```text
member
committee
bill
company
industry
agency
lobbying client
PAC/donor
federal award
ticker
```

## Edges

```text
member → sits_on → committee
committee → oversees → agency/industry
bill → assigned_to → committee
bill → affects → industry/company
company → lobbies → bill
company → receives → federal_award
PAC/donor → contributes_to → member
member → trades → ticker
company → belongs_to → sector/industry
```

Edge table:

```sql
policy_edges (
    edge_id TEXT PRIMARY KEY,
    source_type TEXT,
    source_id TEXT,
    target_type TEXT,
    target_id TEXT,
    edge_type TEXT,
    start_date DATE,
    end_date DATE,
    weight NUMERIC,
    source TEXT
)
```

The recent temporal-graph congressional-trading paper uses a similar idea: dynamic graphs combining congressional transactions, lobbying relationships, campaign finance, and other public relationships, with walk-forward validation to avoid look-ahead bias. ([arXiv](https://arxiv.org/abs/2602.05514?utm_source=chatgpt.com "Detecting Information Channels in Congressional Trading via Temporal Graph Learning"))

We don’t start with a temporal graph neural network. We start with engineered graph features.

---

# Phase 4 — Daily feature table

This is the heart of the system.

Each row:

```text
date, ticker
```

Each row only contains features knowable as of that date.

Table:

```sql
daily_policy_features (
    date DATE,
    ticker TEXT,

    -- market features
    market_cap NUMERIC,
    avg_dollar_volume_20d NUMERIC,
    return_20d NUMERIC,
    return_60d NUMERIC,
    return_90d NUMERIC,
    excess_return_20d NUMERIC,
    sector_excess_return_20d NUMERIC,
    volatility_20d NUMERIC,
    rsi_14 NUMERIC,
    close_to_ema20 NUMERIC,
    ema20_slope NUMERIC,

    -- bill features
    bill_activity_score_30d NUMERIC,
    bill_activity_score_90d NUMERIC,
    bill_relevance_score NUMERIC,
    bill_stage_momentum_score NUMERIC,

    -- committee features
    committee_relevance_score NUMERIC,
    committee_power_score NUMERIC,
    relevant_member_count NUMERIC,

    -- lobbying features
    lobbying_spend_90d NUMERIC,
    lobbying_spend_yoy_change NUMERIC,
    specific_bill_lobbying_count_90d NUMERIC,
    lobbying_intensity_score NUMERIC,

    -- campaign/PAC features
    pac_contribution_score_180d NUMERIC,
    committee_member_contribution_score NUMERIC,
    industry_donation_momentum NUMERIC,

    -- federal spending features
    federal_award_amount_90d NUMERIC,
    federal_award_yoy_change NUMERIC,
    agency_exposure_score NUMERIC,

    -- congressional trade-derived features, known only by disclosure date
    disclosed_congress_buy_count_90d NUMERIC,
    disclosed_congress_sell_count_90d NUMERIC,
    disclosed_net_buy_amount_90d NUMERIC,

    PRIMARY KEY (date, ticker)
)
```

---

# Phase 5 — Feature groups, atomized

## Group A — Bill activity score

For each company/ticker/date:

```text
bill_activity_score =
  weighted sum of relevant bill actions over trailing 30/90 days
```

Weights:

```yaml
bill_action_weights:
  introduced: 0.25
  referred_to_committee: 0.50
  committee_hearing: 1.00
  markup: 1.50
  reported_out_of_committee: 2.00
  passed_house: 3.00
  passed_senate: 3.00
  signed_into_law: 5.00
```

Need bill relevance mapping:

```text
bill → sector
bill → industry
bill → company
```

First version can use keywords:

```yaml
semiconductors:
  keywords: ["semiconductor", "chip", "fab", "foundry", "AI accelerator"]

defense:
  keywords: ["defense", "missile", "munitions", "aerospace", "drone", "DoD"]

telecom_broadband:
  keywords: ["broadband", "fiber", "BEAD", "rural internet", "spectrum"]
```

Later version uses embeddings/classification.

---

## Group B — Committee relevance score

For a company:

```text
company sector/industry ↔ committee jurisdiction
```

Example:

```text
Armed Services Committee + defense contractor = high relevance
Energy and Commerce + telecom/healthcare/energy = high relevance
Banking Committee + banks/fintech/housing finance = high relevance
```

Score:

```text
committee_relevance_score =
  sum(member_power_weight × committee_company_overlap)
```

Member power weights:

```yaml
member_role_weights:
  chair: 3.0
  ranking_member: 2.5
  subcommittee_chair: 2.0
  member: 1.0
```

---

## Group C — Lobbying intensity

For ticker/date:

```text
lobbying_intensity =
  trailing_90d_lobbying_spend
  + YoY change
  + number of specific bills lobbied
  + relevance of those bills
```

Example features:

```text
lobbying_spend_90d
lobbying_spend_365d
lobbying_spend_yoy_pct
specific_bill_count_90d
lobbying_bill_relevance_score
```

---

## Group D — Campaign/PAC relationship score

For company/industry to member/committee:

```text
PAC flow to relevant committee members
```

Feature examples:

```text
industry_pac_to_relevant_committee_180d
company_pac_to_relevant_member_180d
pac_flow_yoy_change
donor_cluster_score
```

This must be handled carefully. It is not “this donation caused this trade.” It is relationship-density signal.

---

## Group E — Federal spending score

For ticker/date:

```text
contract_momentum =
  recent federal awards
  compared to trailing history
```

Features:

```text
federal_award_amount_30d
federal_award_amount_90d
federal_award_amount_365d
federal_award_yoy_change
agency_concentration
contract_type_score
```

This could be especially useful in:

```text
defense
telecom/broadband
healthcare IT
energy
cybersecurity
infrastructure
government contractors
```

---

## Group F — Market confirmation

We do not buy policy stories alone.

Features:

```text
stock_return_20d
stock_return_60d
stock_excess_return_20d
sector_return_20d
sector_excess_return_20d
RSI_14
RSI_recovery_score
EMA_20_slope
price_to_EMA_20
volatility_20d
volume_surge_20d
```

This prevents the model from buying dead-policy narratives that the market is ignoring.

---

# Phase 6 — Labels

We need several labels.

## Label 1 — 60-day excess return

```python
future_60d_excess_return =
    stock_return_t_to_t60 - spy_return_t_to_t60
```

Table:

```sql
daily_labels (
    date DATE,
    ticker TEXT,
    future_return_30d NUMERIC,
    future_return_60d NUMERIC,
    future_return_90d NUMERIC,
    future_spy_return_30d NUMERIC,
    future_spy_return_60d NUMERIC,
    future_spy_return_90d NUMERIC,
    future_excess_return_30d NUMERIC,
    future_excess_return_60d NUMERIC,
    future_excess_return_90d NUMERIC,
    future_congress_buy_60d BOOLEAN,
    future_congress_sell_60d BOOLEAN,
    PRIMARY KEY (date, ticker)
)
```

## Label 2 — future congressional buy

```text
future_congress_buy_60d = true if a congressional buy transaction occurs in next 60 trading days
```

But be careful: this label uses transaction date for research. For live signal features, we still only know disclosures when disclosed.

## Label 3 — top quantile

For ranking:

```text
top_decile_60d = 1 if future_excess_return_60d in top 10% of universe that day
```

That may be a better training target than raw return.

---

# Phase 7 — No-leakage rules

These are laws. No exceptions.

## Rule 1

```text
Feature date must be less than or equal to prediction date.
```

## Rule 2

```text
Congressional trades are not public until disclosure_date.
```

## Rule 3

```text
Bill action is known on action_date, not before.
```

## Rule 4

```text
Lobbying reports are known only after filing/publication date, not period end.
```

## Rule 5

```text
Campaign finance data is known only after public availability date.
```

## Rule 6

```text
Federal awards are known only after award/publication date.
```

## Rule 7

```text
All scalers, imputers, encoders, and target transforms must be fit only on training folds.
```

## Rule 8

```text
No random train/test split.
```

Use walk-forward only.

The temporal graph paper explicitly emphasizes walk-forward validation and respecting information availability constraints to avoid look-ahead bias. ([arXiv](https://arxiv.org/abs/2602.05514?utm_source=chatgpt.com "Detecting Information Channels in Congressional Trading via Temporal Graph Learning"))

---

# Phase 8 — Models

We build three models, but not all at once.

## Model A — Congress-buy probability model

Question:

```text
Does this company look like something Congress may buy in the next 60 days?
```

Target:

```text
future_congress_buy_60d
```

Inputs:

```text
policy features
market features
relationship features
```

Output:

```text
congress_buy_probability_60d
```

Model type:

```text
LightGBM classifier
```

Why this model matters:

```text
It tries to learn the shape of congressional opportunity zones.
```

But this is not the trading model.

---

## Model B — Policy alpha return model

Question:

```text
Which stocks will beat SPY over the next 60 days?
```

Target:

```text
future_excess_return_60d
```

Inputs:

```text
all features
+ Model A out-of-sample congress-buy probability
```

Output:

```text
expected_60d_excess_return
```

Model type:

```text
LightGBM regressor or ranker
```

Important: Model B can only use Model A predictions that were generated out-of-sample during training. Otherwise stacked leakage.

---

## Model C — Portfolio entry filter

Question:

```text
Given this high-ranking stock, is it worth entering now?
```

Target:

```text
future_60d_net_excess_return_after_costs > threshold
```

Inputs:

```text
Model B score
cost estimate
current rank
turnover impact
RSI/EMA confirmation
volatility
sector exposure
```

Output:

```text
trade_allowed_probability
```

This comes later. Do not start here.

---

# Phase 9 — Validation design

Use walk-forward.

Example:

```text
Train: 2013–2017
Gap: 90 trading days
Test: 2018

Train: 2013–2018
Gap: 90 trading days
Test: 2019

Train: 2013–2019
Gap: 90 trading days
Test: 2020

...
```

Because the target is 60–90 days, the purge gap should be at least:

```text
90 trading days
```

You had mentioned 63 days before. For this project, because we are explicitly using 90-day labels, I’d use a 90-trading-day purge.

Metrics:

```text
IC / rank correlation
top-decile future excess return
top-quintile future excess return
long-only portfolio return
net return after costs
turnover
max drawdown
Sharpe
Sortino
hit rate vs SPY
rolling 1-year and 3-year outperformance vs SPY
```

---

# Phase 10 — Portfolio construction

This is not optional. The model ranking alone does not make money.

## Portfolio rules

```yaml
portfolio:
  holdings: 25_to_50
  rebalance_frequency: monthly
  max_position_weight: 0.04
  min_position_weight: 0.01
  max_sector_weight: 0.25
  max_monthly_turnover: 0.50
  buy_threshold_rank_percentile: 0.95
  hold_threshold_rank_percentile: 0.80
  sell_threshold_rank_percentile: 0.60
```

Interpretation:

```text
Buy top 5%.
Hold while still top 20%.
Sell if falls below top 40% or risk/cost conditions fail.
```

This avoids full monthly churn.

## Trade approval rule

```python
trade_allowed = (
    expected_60d_excess_return > estimated_cost + required_margin
    and monthly_turnover_after_trade <= 0.50
    and sector_weight_after_trade <= max_sector_weight
    and liquidity_ok
)
```

## Required margin

Example:

```text
estimated cost: 0.20%
required margin: 1.00%
trade only if expected excess return > 1.20%
```

This prevents tiny fake edges from generating trades.

---

# Phase 11 — Transaction cost model

Your source explicitly says square-root market impact models matter and linear cost models can be misleading.

Use:

```text
impact = coefficient × volatility × sqrt(order_size / average_daily_volume)
```

Pseudo-code:

```python
def square_root_impact_bps(order_dollars, adv_dollars, daily_volatility, coefficient=0.75):
    if adv_dollars <= 0:
        return float("inf")

    participation = order_dollars / adv_dollars
    impact_decimal = coefficient * daily_volatility * participation ** 0.5
    return impact_decimal * 10_000
```

Total cost:

```python
total_cost_bps = spread_bps + commission_bps + impact_bps
```

Even if retail commission is zero, spread and impact are not zero. The market still takes its lunch money.

---

# Phase 12 — Backtest reports

Every run produces a promotion report.

```text
Model:
Kairos Policy Alpha v0.1

Universe:
Large-cap liquid U.S. stocks

Target:
60-day excess return vs SPY

Validation:
Walk-forward
90-day purge
No random split

Performance:
Strategy CAGR
SPY CAGR
Excess CAGR
Sharpe
Max drawdown
Monthly turnover
Cost drag
Percent years beating SPY
Rolling 3-year win rate
Best year
Worst year
Sector attribution
Top contributor concentration

Decision:
Promote / reject / revise
```

Reject examples:

```text
Reject: beats SPY only because of semiconductors in 2023–2024.
Reject: gross alpha positive but net alpha disappears after costs.
Reject: turnover exceeds 50% monthly.
Reject: performance depends on using trade_date data before disclosure_date.
```

That last one is the “backtest felony” bucket.

---

# Phase 13 — Repo structure

```text
kairos-policy-alpha/
  README.md
  pyproject.toml
  configs/
    universe.yaml
    features.yaml
    validation.yaml
    portfolio.yaml
    cost_model.yaml

  data_ingest/
    congress_trades.py
    congress_bills.py
    committees.py
    lobbying.py
    fec.py
    usaspending.py
    market_data.py

  entity_resolution/
    normalize_names.py
    match_companies.py
    match_members.py
    review_queue.py

  graph/
    build_edges.py
    relationship_scores.py

  features/
    bill_features.py
    committee_features.py
    lobbying_features.py
    pac_features.py
    federal_award_features.py
    market_features.py
    congress_trade_features.py
    feature_table.py

  labels/
    excess_returns.py
    future_congress_buy.py

  validation/
    walk_forward.py
    leakage_checks.py
    purging.py

  models/
    congress_buy_model.py
    policy_alpha_ranker.py
    entry_filter.py

  portfolio/
    construction.py
    turnover.py
    sector_caps.py
    rebalance.py

  execution/
    square_root_impact.py
    spread_model.py
    cost_model.py

  backtest/
    engine.py
    accounting.py
    benchmark.py

  reports/
    promotion_report.py
    attribution.py

  tests/
    test_no_leakage.py
    test_disclosure_dates.py
    test_entity_resolution.py
    test_turnover.py
    test_cost_model.py
    test_walk_forward.py
```

---

# Phase 14 — Atomic build order

This is the order I would actually build it.

## Milestone 1 — Skeleton and market baseline

Deliverables:

```text
repo created
config files
market data loader
SPY benchmark loader
universe builder
30/60/90-day excess-return labels
walk-forward splitter
```

Success check:

```text
Can build date/ticker rows with future excess-return labels and no model yet.
```

---

## Milestone 2 — Rule-free baseline model

Deliverables:

```text
market-only LightGBM ranker
features: price, volume, volatility, sector
target: 60-day excess return
walk-forward report
```

Purpose:

```text
Establish baseline before policy data.
```

If policy features later do not beat this, they are decoration, not alpha.

---

## Milestone 3 — Congressional trade ingestion

Deliverables:

```text
congress trade parser/provider connector
trade normalization
ticker/entity mapping
disclosure-date handling
tests proving trade not visible before disclosure date
```

Success check:

```text
For every trade:
transaction_date <= disclosure_date
model_public_date = disclosure_date
```

---

## Milestone 4 — Congress-buy label model

Deliverables:

```text
future_congress_buy_60d label
basic Model A classifier
walk-forward report
```

Purpose:

```text
Can we predict congressional buying zones at all?
```

---

## Milestone 5 — Bills and committees

Deliverables:

```text
Congress.gov API connector
bill table
bill actions
committee mapping
sector/bill keyword mapper
bill activity features
committee relevance features
```

Congress.gov API is the official structured access point we’d use for bill/action data. ([Congress.gov API](https://api.congress.gov/?utm_source=chatgpt.com "Congress.gov API"))

Success check:

```text
Can compute daily bill/committee relevance scores for each ticker.
```

---

## Milestone 6 — Federal spending

Deliverables:

```text
USAspending connector
award normalization
recipient → ticker mapping
federal award features
```

USAspending is the official open data source for federal award data and has an API for U.S. government spending data. ([USAspending](https://www.usaspending.gov/?utm_source=chatgpt.com "USAspending: Government Spending Open Data"))

Success check:

```text
Can compute 30/90/365-day federal award momentum by ticker.
```

---

## Milestone 7 — Lobbying and campaign finance

Deliverables:

```text
OpenFEC connector
OpenSecrets/lobbying data source connector or import path
lobbying spend features
PAC/contribution relationship features
```

OpenFEC provides official campaign-finance API access and nightly-updated FEC data. ([OpenFEC API](https://api.open.fec.gov/developers/?utm_source=chatgpt.com "OpenFEC API Documentation"))

Success check:

```text
Can compute lobbying/PAC relationship scores without future filing leakage.
```

---

## Milestone 8 — Policy alpha ranker

Deliverables:

```text
Model B: 60-day excess-return ranker
features: market + policy + Model A OOS score
walk-forward report
feature importance
ablation tests
```

Ablation tests:

```text
market-only
market + congress trades
market + bills
market + lobbying
market + federal spending
market + all policy
```

This tells us what actually adds value.

---

## Milestone 9 — Portfolio simulator

Deliverables:

```text
monthly rebalance simulator
25–50 holdings
buy/hold/sell bands
sector caps
turnover cap
SPY comparison
```

Success check:

```text
Can run strategy net of turnover constraints before cost model.
```

---

## Milestone 10 — Cost model

Deliverables:

```text
spread model
square-root impact model
net performance report
```

Success check:

```text
Gross and net return both reported.
No promotion if alpha vanishes after costs.
```

---

## Milestone 11 — Promotion report

Deliverables:

```text
HTML/Markdown report
charts/tables
SPY comparison
rolling-window performance
sector attribution
top holdings
rejection reasons
```

---

# Phase 15 — First experiment matrix

We should not run one model and declare victory.

Run these:

```text
Experiment 001:
Market-only 60d ranker

Experiment 002:
Market + congressional disclosed-trade features

Experiment 003:
Market + bill/committee features

Experiment 004:
Market + lobbying features

Experiment 005:
Market + federal awards

Experiment 006:
Market + all policy features

Experiment 007:
All policy + Model A congress-buy probability

Experiment 008:
All policy + RSI/EMA entry filter

Experiment 009:
All policy + monthly portfolio

Experiment 010:
All policy + monthly portfolio + costs + turnover gates
```

Only Experiment 010 matters for “does this trade.”

---

# Phase 16 — What we are trying to prove

There are three hypotheses.

## Hypothesis 1

```text
Public policy-pressure features predict future congressional buying.
```

Model A tests this.

## Hypothesis 2

```text
Public policy-pressure features predict 30/60/90-day excess returns versus SPY.
```

Model B tests this.

## Hypothesis 3

```text
A portfolio built from these predictions beats SPY after costs and turnover constraints.
```

Portfolio simulator tests this.

If 1 is true but 2 is false, then we can predict what Congress buys, but it does not help make money.

If 2 is true but 3 is false, then the signal exists but is not tradable after constraints.

If all three are true, we have something worth paper trading.

---

# Phase 17 — What the first version should not do

Do **not** start with:

```text
graph neural networks
reinforcement learning
options
shorting
small caps
intraday trading
daily rebalancing
copying delayed trades directly
```

Those are later, if ever.

First version:

```text
large-cap
long-only
monthly rebalance
60-day horizon
supervised ranking
strict no-leakage
cost/turnover gates
```

That is how we avoid building a casino wearing a lab coat.

---

# My recommended first sprint

Sprint 1 should be boring and foundational:

```text
1. Create repo structure
2. Build universe
3. Build market feature table
4. Build 30/60/90-day excess-return labels
5. Build walk-forward splitter with 90-day purge
6. Train market-only baseline model
7. Produce baseline SPY comparison report
```

No congressional data yet.

Why?

Because before we prove policy data adds alpha, we need a baseline to beat. Otherwise we will not know whether the “Congress edge” is real or just regular momentum/sector exposure with a flag pin stuck in it.

---

# The atomic definition of done for v0.1

v0.1 is done when we can say:

```text
Using only market data, we can train a no-leakage 60-day large-cap excess-return ranker and compare a monthly portfolio against SPY net of basic costs.
```

v0.2:

```text
Add congressional trade disclosures correctly using disclosure date.
```

v0.3:

```text
Add bills and committee relevance.
```

v0.4:

```text
Add lobbying/PAC/federal spending features.
```

v1.0:

```text
Full policy-alpha model with portfolio simulator, square-root costs, turnover gates, and promotion report.
```

That is the path I’d trust.
