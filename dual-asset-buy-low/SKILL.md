---
name: dual-asset-buy-low
description: Recurring DCA via Dual Asset products — buy target coin at strike price, with balance check, split orders, and debug mode.
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
> This applies to: (1) script execution via `buy_low.py` (built into `bybit_client.py`), (2) agent direct `curl` or HTTP tool calls for verification/debugging, (3) any MCP tool or `fetch` hitting `api.bybit.com` / `api-testnet.bybit.com`. Non-compliant requests (missing either header) are **prohibited**. Always include both headers when constructing any API call manually.

# Dual Asset Buy-Low Recurring

Periodically uses Bybit Dual Asset products to attempt purchasing a target cryptocurrency below market price. Automatically selects the optimal strike price, subscribes when conditions match, and rolls over on expiry if not filled.

## Prerequisites

**Default behavior:** The agent should use mainnet by default. Do NOT ask the user whether to use mainnet or testnet — just proceed with mainnet unless the user explicitly requests `--testnet` or `--debug` mode.

### API Key Binding (Required)

Configure Bybit API credentials before use:

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

Run with `--debug` flag to dry-run the strategy without API credentials. Debug mode fetches public product data, evaluates conditions, and outputs planned order request bodies without executing.

### Testnet Mode (API Key Required)

Run with `--testnet` flag to execute the strategy on Bybit testnet. Requires API key configured for testnet. Orders are executed without CONFIRM prompt. Useful for testing with real API calls without risking real funds.

## Strategy Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| targetCoin | Target coin to accumulate | BTC |
| quoteCoin | Quote coin for investment | USDT |
| targetBuyPrice | Maximum acceptable strike price (required) | - |
| investPerRound | Investment per round in quote coin | 500 |
| minPremiumYield | Minimum annualized premium yield (10%) | 0.10 |
| recurringSchedule | Execution frequency: daily/weekly | daily |
| preferredDuration | Duration preference: shortest/longest/balanced | shortest |
| debug | Debug mode: dry-run without API key | false |
| testnet | Use testnet API (requires API key) | false |

## Required Parameter Collection

Before executing the strategy, the agent MUST verify that all required parameters are provided by the user. If any required parameter is missing, the agent MUST ask the user before proceeding — never guess or use a default for required fields.

**Required parameters (no default — must ask user):**
- `targetBuyPrice`: Ask the user what maximum strike price they're willing to accept. Provide the current market price as context to help them decide.
- `investPerRound`: Ask the user how much they want to invest per round (in quote coin). Default suggestion is 500, but must be confirmed by user.

**Interaction flow:**
1. If the user does not specify `targetBuyPrice`, first fetch the current market price of the target coin via the product-extra-info API (or use debug mode public data).
2. Present the current price to the user and ask them to set their target buy price.
3. Ask the user to confirm the investment amount per round (`investPerRound`).
4. Only proceed with execution after the user confirms both target price and investment amount.

## Strategy Logic

### Step 1: Check Previous Order Settlement
If a previous order is still active (current time < recorded settlement time), skip this round to avoid duplicate subscriptions.

### Step 2: Fetch Dual Asset Products
Pull all available DualAssets products filtered by `baseCoin=targetCoin` and `quoteCoin=quoteCoin`. If no matching products exist, inform the user and exit.

### Step 3: Check FUND Account Balance
Query FUND account balance for `quoteCoin`. If available balance < `investPerRound`, skip this round.

### Step 4: Get Quote Details
Retrieve strike prices and premium yields for each matching product.

### Step 5: Condition Check
Effective buy price = strike price (directly). Proceed only if: strike price ≤ `targetBuyPrice` AND annualized premium ≥ `minPremiumYield`.

### Step 6: Select Optimal Strike
Based on `preferredDuration`: shortest duration first, longest duration first, or balanced. When multiple candidates qualify within the same duration tier, select the strike price **farthest from current market price** (deepest discount).

### Step 7: Execute Subscription (Dynamic Split Orders)
If `investPerRound` exceeds the product's `maxInvestmentAmount`, split into multiple sub-orders. Each sub-order size = `min(remaining, maxInvestmentAmount * 80%)`. Before each sub-order:
- Query `GET /v5/earn/advance/product-extra-info` to get the latest `maxInvestmentAmount` for the selected strike
- Wait 5 seconds after the previous sub-order
- Re-check conditions (strike ≤ targetBuyPrice AND premium ≥ minPremiumYield) before execution
- If conditions no longer met, stop remaining sub-orders for this round

Subscribe using FUND account with `quoteCoin`.

### Step 8: Record Settlement Time
After successful subscription, record the product's `settlementTime`. Next rounds will skip until this time is reached.

### Step 9: Recurring Loop
Strategy loops every `recurringSchedule` (default: daily, 24h cycle).

## Scripts & Reference

### Reference: `reference/dual-asset-api.md`
Complete API specification for Dual Asset endpoints (product listing, quote details, balance check, order placement, position monitoring, authentication, rate limits).

### Script: `scripts/bybit_client.py`
Bybit API client with HMAC-SHA256 authentication and mandatory headers.
- `BybitClient(env_override=None)` — Initialize client (reads BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_ENV from environment)
- `client.verify_credentials()` — Validate API key/secret, check clock sync
- `client.get(endpoint, params=None)` — Authenticated GET request with rate limiting
- `client.post(endpoint, body=None)` — Authenticated POST request with rate limiting
- `client.confirm_operation(summary)` — Display summary and prompt CONFIRM (auto-confirms on testnet)

### Script: `scripts/buy_low.py`
Main strategy script for Dual Asset BuyLow recurring DCA.
- `get_fund_balance(client, coin)` — Query FUND account balance
- `get_dual_asset_products(client, target_coin, quote_coin)` — Fetch available products (filtered by coin pair and status)
- `get_product_quotes(client, product_id)` — Get strike prices, APY, maxInvestmentAmount from product-extra-info
- `find_best_quote(products, client, target_price, min_premium, preferred_duration)` — Select optimal product/strike based on criteria
- `check_conditions(client, product_id, target_price, min_premium)` — Re-verify quote conditions and get fresh apyE8
- `get_max_order_limit(client, product_id, select_price)` — Get current maxInvestmentAmount for a strike
- `build_order_body(best, amount, quote_coin, order_link_id)` — Construct POST body for place-order
- `execute_with_split(client, best, invest_amount, quote_coin, target_price, min_premium)` — Execute with dynamic split orders (refreshes apyE8 before each sub-order)

**Run:** `python scripts/buy_low.py --target-coin BTC --target-price 60000 [--debug] [--testnet]`

### Agent Execution Guidance

> **IMPORTANT: Script-First Approach**
>
> Before making direct API calls, the agent MUST first check if the required functionality is already implemented in the scripts above.
> - **Preferred:** Execute strategy via `python scripts/buy_low.py` with appropriate flags (`--debug` for dry-run, `--testnet` for test execution, no flag for mainnet)
> - **Fallback only:** If the scripts do not cover a specific operation (e.g., querying a single balance, checking a specific position, or one-off manual operations), the agent may construct API requests directly using the reference documentation
> - The scripts already handle: authentication, rate limiting, mandatory headers, order confirmation, split orders, error handling, and logging
> - Do NOT re-implement existing script functionality via raw API calls

## API Endpoints

All requests MUST include:
- `User-Agent: bybit-skill/1.3.0`
- `X-Referer: bybit-skill`

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | /v5/earn/advance/product?category=DualAssets | List Dual Asset products |
| GET | /v5/earn/advance/product-extra-info?category=DualAssets | Get strike prices and premiums |
| POST | /v5/earn/advance/place-order | Subscribe to Dual Asset product |
| GET | /v5/earn/advance/position?category=DualAssets | Monitor positions and settlements |
| GET | /v5/asset/transfer/query-account-coins-balance | Check FUND account balance |

## Risk Disclaimer

This strategy leverages the structural properties of Dual Asset products for DCA. **Risk warning**: If the market drops significantly below the strike price, you will buy at the strike price and may face further downside. This is suitable for users with long-term bullish conviction on the target asset who accept interim drawdowns.

## Installation & Usage

```bash
pip install requests

# Basic usage
python scripts/buy_low.py --target-coin BTC --target-price 60000

# Custom quote coin and investment
python scripts/buy_low.py --target-coin ETH --target-price 2800 \
  --quote-coin USDC --invest 1000 --schedule weekly

# Debug mode (no API key needed)
python scripts/buy_low.py --target-coin BTC --target-price 60000 --debug

# Testnet mode (API key required, real orders on testnet)
python scripts/buy_low.py --target-coin BTC --target-price 60000 --testnet
```

## Confirmation Mechanism

Each Dual Asset subscription on Mainnet requires user confirmation showing: coin, amount, strike price, premium yield, and duration. Type "CONFIRM" to execute. Testnet executes without confirmation.
