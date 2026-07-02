---
name: event-driven-doublewin
description: Scan economic calendars and crypto news, rate events via AI agent, subscribe to DoubleWin products to profit from volatility spikes.
metadata:
  version: 2.0.0
  author: Bybit Official
  updated: 2026-05-17
license: MIT
---

> **MANDATORY HEADERS — ALL API INTERACTIONS**
>
> Every HTTP request to any Bybit API endpoint MUST include:
> ```
> User-Agent: bybit-skill/1.3.0
> X-Referer: bybit-skill
> ```
> This applies to: (1) script execution via `doublewin_hunter.py` (built into `bybit_client.py`), (2) agent direct `curl` or HTTP tool calls for verification/debugging, (3) any MCP tool or `fetch` hitting `api.bybit.com` / `api-testnet.bybit.com`. Non-compliant requests (missing either header) are **prohibited**. Always include both headers when constructing any API call manually.

# Event-Driven DoubleWin Hunter

Scans economic calendars and crypto news sources every 8 hours, identifies high-impact events, and automatically subscribes to DoubleWin products to profit from volatility spikes around those events.

## Prerequisites

**Default behavior:** The agent should use mainnet by default. Do NOT ask the user whether to use mainnet or testnet — just proceed with mainnet unless the user explicitly requests `--testnet` or `--debug` mode.

### API Key Binding (Required)

```bash
export BYBIT_API_KEY="your_api_key"
export BYBIT_API_SECRET="your_secret_key"
export BYBIT_ENV="mainnet"  # or "testnet"
```

Required permissions: **Read + Trade** (never enable Withdraw).

Verify:
```bash
curl -H "User-Agent: bybit-skill/1.3.0" \
     -H "X-Referer: bybit-skill" \
     https://api.bybit.com/v5/market/time
```

### Debug Mode (No API Key Needed)

Run with `--debug` flag to dry-run the strategy without API credentials. Debug mode fetches public news sources, runs interactive event rating, and outputs planned order request bodies without executing.

### Testnet Mode (API Key Required)

Run with `--testnet` flag to execute the strategy on Bybit testnet. Requires API key configured for testnet. Orders are executed without CONFIRM prompt. Useful for testing with real API calls without risking real funds.

## Strategy Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| targetCoin | Underlying asset for DoubleWin | BTC |
| capitalPerTrade | USDT per trade (max 1000) | 200 |
| entryWindowHours | Hours before event to enter position | 24 |
| minEventLevel | Minimum event level: medium/high | medium |
| preferredLeverage | Leverage selection: auto/low/high | auto |
| debug | Debug mode: dry-run without API key | false |
| testnet | Use testnet API (requires API key) | false |

**Note:** Account type is fixed to FUND. Maximum capital per trade is 1000 USDT.

## Data Sources

The strategy fetches events from **four mandatory platforms** every scan cycle:

| Source | Type | URL |
|--------|------|-----|
| Investing.com | Economic Calendar | investing.com/economic-calendar/ |
| CoinDesk | Crypto News RSS | coindesk.com/arc/outboundfeeds/rss/ |
| CoinTelegraph | Crypto News RSS | cointelegraph.com/rss |
| The Block | Crypto News RSS | theblock.co/rss.xml |

All events must have a determined time (publication date or scheduled release time). Events without parseable timestamps are discarded.

## Strategy Logic

### Step 1: Check Previous Settlement
If a previous order is still active (current time < recorded settlement time), skip this round to avoid duplicate subscriptions.

### Step 2: Fetch Events from All Data Sources
Attempt all four sources (Investing.com, CoinDesk, CoinTelegraph, The Block). Collect events with determined timestamps.

### Step 3: Dual Time Window Filter
Events are filtered using two time windows:
- **Upcoming events** (economic calendar with scheduled future times): event time is within `entryWindowHours` in the future → enter position before the event occurs.
- **Recent news** (RSS with publication timestamps): published within `entryWindowHours` in the past → treat as "event just happened / still unfolding", enter position to capture ongoing volatility.

This dual-window approach handles both scheduled future events and breaking news that triggers immediate market moves.

### Step 4: Event Deduplication (AI-Assisted)
Two-layer deduplication:
1. **Exact ID match**: If the event's MD5 ID (title+source+time) matches a history entry, skip immediately.
2. **AI agent semantic judgment**: Present the candidate event alongside recent trade history to the AI agent. The agent determines whether the candidate refers to the same underlying event as any previously traded event — even if titles differ slightly (e.g., different headlines covering the same FOMC decision). In debug/testnet mode, auto-judges as "not duplicate".

### Step 5: AI Agent Event Rating (Decision)
Present each event interactively to the AI agent for evaluation. The agent rates the event's expected impact on the target coin's price: **high**, **medium**, **low**, or **skip**. No keyword-based automation — the agent uses its own judgment.

### Step 6: Check FUND Account Balance
Query FUND account USDT balance. If balance < `capitalPerTrade`, skip this round.

### Step 7: Fetch DoubleWin Products
Query available DoubleWin products for `targetCoin`.

### Step 8: Product Selection (Settlement > Event Time)
Select a product whose `settlementTime` is **after** the event's expected time. This ensures the product covers the volatility window of the event.

### Step 9: Select Leverage
Based on the agent's rating and leverage preference:
- High impact + auto → highest leverage
- Medium impact + auto → lowest leverage
- Manual override: low/high as specified

### Step 10: Execute Order
Subscribe to DoubleWin with `accountType=FUND`. On success: record settlement time, save event to dedup history.

> Strategy scans every 8 hours (default).

## Event Rating

Event rating is performed interactively by the AI agent executing this skill. For each candidate event, the script presents:
- Source platform
- Event title and summary
- Event time
- Target coin

The agent provides a rating based on its assessment of the event's likely market impact. This replaces keyword-based automation with intelligent judgment.

## Debug Mode

When `--debug` is specified:
- No API key or secret required
- News sources are fetched normally (public RSS feeds)
- Interactive event rating still runs
- For qualifying events: outputs planned product, leverage, and full API request body as JSON
- No actual POST requests executed
- Exits after one scan cycle (no loop)

## Scripts & Reference

### Reference: `reference/doublewin-api.md`
Complete API specification for DoubleWin endpoints (product listing, leverage/pricing details, balance check, order placement, position monitoring, order history).

### Script: `scripts/bybit_client.py`
Bybit API client with HMAC-SHA256 authentication and mandatory headers.
- `BybitClient(env_override=None)` — Initialize client (reads BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_ENV from environment)
- `client.verify_credentials()` — Validate API key/secret, check clock sync
- `client.get(endpoint, params=None)` — Authenticated GET request with rate limiting
- `client.post(endpoint, body=None)` — Authenticated POST request with rate limiting
- `client.confirm_operation(summary)` — Display summary and prompt CONFIRM (auto-confirms on testnet)

### Script: `scripts/doublewin_hunter.py`
Main strategy script for event-driven DoubleWin trading.
- `scan_all_sources()` — Fetch events from all 4 platforms (Investing.com, CoinDesk, CoinTelegraph, The Block)
- `fetch_rss_feed(url, source_name)` — Parse RSS feed and extract events with timestamps
- `fetch_investing_calendar()` — Scrape Investing.com economic calendar
- `is_duplicate(event, history)` — Two-layer dedup: exact ID match + AI semantic judgment
- `request_agent_rating(event, target_coin)` — AI agent rates event impact (high/medium/low/skip)
- `get_fund_balance(client, coin)` — Query FUND account USDT balance
- `get_doublewin_products(client, target_coin)` — Fetch available DoubleWin products
- `get_product_details(client, product_id)` — Get leverage options and pricing
- `select_product_with_leverage(client, products, event_time_ms, event_level, preferred_leverage)` — Select product with settlement > event time
- `execute_doublewin(client, product, leverage_info, amount, event_desc)` — Subscribe to DoubleWin
- `load_dedup_history()` / `save_dedup_history(history)` — Manage local trade history (last 200 entries)

**Run:** `python scripts/doublewin_hunter.py --target-coin BTC [--debug] [--testnet]`

### Agent Execution Guidance

> **IMPORTANT: Script-First Approach**
>
> Before making direct API calls, the agent MUST first check if the required functionality is already implemented in the scripts above.
> - **Preferred:** Execute strategy via `python scripts/doublewin_hunter.py` with appropriate flags (`--debug` for dry-run, `--testnet` for test execution, no flag for mainnet)
> - **Fallback only:** If the scripts do not cover a specific operation (e.g., querying a single balance, checking a specific position, or one-off manual operations), the agent may construct API requests directly using the reference documentation
> - The scripts already handle: authentication, rate limiting, mandatory headers, order confirmation, event deduplication, error handling, and logging
> - Do NOT re-implement existing script functionality via raw API calls

## API Endpoints

All requests MUST include:
- `User-Agent: bybit-skill/1.3.0`
- `X-Referer: bybit-skill`

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | /v5/earn/advance/product?category=DoubleWin | List DoubleWin products |
| GET | /v5/earn/advance/product-extra-info?category=DoubleWin | Leverage and pricing |
| POST | /v5/earn/advance/place-order | Subscribe to DoubleWin |
| GET | /v5/earn/advance/position?category=DoubleWin | Monitor positions |
| GET | /v5/earn/advance/order?category=DoubleWin | Settlement history |
| GET | /v5/asset/transfer/query-account-coins-balance | Check FUND balance |

## Risk Disclaimer

This strategy profits from high volatility events but **DoubleWin products can result in total principal loss** if price movement is insufficient. Additional risks:
- Event impact assessment relies on the agent's judgment, which may be incorrect
- Historical volatility patterns may not predict future behavior
- High leverage amplifies both gains and losses
- Black swan events may overwhelm any structured product

Only suitable for users who understand structured products and accept the risk of total principal loss.

## Installation & Usage

```bash
pip install requests

# Basic usage
python scripts/doublewin_hunter.py --target-coin BTC

# Conservative settings
python scripts/doublewin_hunter.py --target-coin ETH --capital-per-trade 100 \
  --min-level high --leverage low

# Debug mode (no API key needed)
python scripts/doublewin_hunter.py --target-coin BTC --debug

# Testnet mode (API key required, real orders on testnet)
python scripts/doublewin_hunter.py --target-coin BTC --testnet
```

## Confirmation Mechanism

All DoubleWin subscriptions on Mainnet require explicit confirmation. The confirmation card shows: underlying asset, amount, leverage, event trigger, and duration. Type "CONFIRM" to execute. Testnet executes without confirmation.
