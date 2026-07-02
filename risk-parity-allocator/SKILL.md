---
name: risk-parity-allocator
description: Allocate Earn capital using APR/risk-parity weighting — each product weighted by risk-adjusted return across multiple Earn categories.
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
> This applies to: (1) script execution via `risk_parity.py` (built into `bybit_client.py`), (2) agent direct `curl` or HTTP tool calls for verification/debugging, (3) any MCP tool or `fetch` hitting `api.bybit.com` / `api-testnet.bybit.com`. Non-compliant requests (missing either header) are **prohibited**. Always include both headers when constructing any API call manually.

# Risk-Parity Earn Allocator

Applies risk-adjusted return weighting to Bybit Earn allocation. Assigns risk scores to each product type, fetches current APR, then allocates by `APR/risk` ratio — products with better risk-adjusted returns get higher allocation.

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

Run with `--debug` flag to dry-run. Outputs planned allocations, product selections, and API request bodies without executing.

### Testnet Mode (API Key Required)

Run with `--testnet` flag to execute the strategy on Bybit testnet. Requires API key configured for testnet. Orders are executed without CONFIRM prompt. Total capital is auto-detected from testnet account.

## Strategy Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| totalCapital | Total capital (debug mode required; live/testnet auto-detected) | auto |
| coin | Investment coin (required) | - |
| allowedProductTypes | Allowed product types | FlexibleSaving,OnChain,LiquidityMining,DualAssets,DoubleWin |
| allowedRiskLevels | Allowed risk levels (1-5) | 1,2,3,4,5 |
| driftThreshold | Rebalance drift threshold (10%) | 0.1 |
| maxSingleAllocation | Maximum allocation per product (75%) | 0.75 |
| minSingleAllocation | Minimum allocation per product (0%) | 0.00 |
| dualAssetPreference | Dual asset selection preference | nearest-farthest |
| dualAssetMaxDays | Dual asset max duration in days | 1 |
| debug | Debug mode: dry-run without API key | false |
| testnet | Use testnet API (requires API key) | false |

**Note:** Account type is fixed to FUND. The skill only manages allocation for the specified coin.

**Capital auto-detection (live/testnet mode):** In non-debug mode, total capital is automatically calculated as FUND account balance + all existing earn positions for the specified coin. The agent should NOT ask the user for capital amount — it is derived from the user's actual holdings.

**Default behavior:** `dualAssetMaxDays` defaults to 1 day. The agent should NOT ask the user about this parameter unless the user explicitly mentions duration preferences — just use the default.

## Risk Scores

| Product Type | Risk Score | Rationale |
|-------------|------------|-----------|
| FlexibleSaving | 1 | No lock, no directional risk |
| OnChain | 2 | Smart contract risk |
| LiquidityMining | 3 | Impermanent loss risk |
| DualAssets | 4 | Directional/settlement risk |
| DoubleWin | 5 | Potential total principal loss |

## Strategy Logic

### Step 1: Coin Support Check
For each allowed product type, verify the specified investment coin is supported:
- FlexibleSaving/OnChain/LiquidityMining: Query product API with `coin` parameter
- DualAssets: If coin=USDT, check for BuyLow products (quoteCoin=USDT); if coin≠USDT, check for SellHigh products (baseCoin=coin)
- DoubleWin: Only supports USDT investment

Unsupported product types are automatically removed from the allocation.

### Step 2: Fetch Product APR
For each supported product type, query the current best available APR. DoubleWin has no APR (returns 0).

### Step 3: Calculate Weights (APR/Risk)
`weight_i = (APR_i / risk_i) / Σ(APR_j / risk_j)` — products with better risk-adjusted returns get higher weight.

**DoubleWin special rule:** Fixed 5% allocation, does not participate in APR/risk calculation. If risk level 5 is not in allowedRiskLevels, DoubleWin weight = 0%.

### Step 4: Apply Constraints
Enforce `maxSingleAllocation` and `minSingleAllocation` limits. Normalize to 100%.

### Step 5: Validate Order Amounts
Each product type has minimum and maximum order limits:
- FlexibleSaving: no minimum, no maximum
- OnChain: min 50 USD, max 200,000 USD
- LiquidityMining: min 100 USD, no maximum
- DualAssets: min 50 USD, max 200,000 USD
- DoubleWin: min 50 USD, max 1,000 USD

Allocations below minimum are skipped. Allocations above maximum are capped.

### Step 6: Select Products
- **DualAssets:** If coin=USDT → BuyLow products (quoteCoin=USDT), farthest strike from current price, nearest expiry. If coin≠USDT → SellHigh products (baseCoin=coin), farthest strike, nearest expiry.
- **DoubleWin:** Shortest expiry product available (USDT only)
- **Others:** Highest APR product for the specified coin

### Step 7: Execute Allocation
Subscribe to selected products using FUND account with the specified coin.

### Step 8: Drift Monitoring & Rebalance
Every 24h, recalculate total capital (FUND balance + all earn positions), check actual vs. target weights. If drift > threshold, rebalance:
- Redeem from over-allocated products (FlexibleSaving, OnChain, LiquidityMining only)
- Subscribe to under-allocated products
- **DualAssets and DoubleWin do NOT support early redemption.** If these products are over-allocated, wait for settlement/expiry before rebalancing them. Only subscribe more when under-allocated and FUND balance is available.
- **Liquidity Mining redemptions:** Always specify `coin` as the user's designated investment coin in the redeem request body, ensuring the redeemed amount is received in the investment currency (not the pool's paired asset).
- **Liquidity Mining rebalance warning:** When the portfolio includes Liquidity Mining products and risk level 3 is allowed, the agent MUST warn the user on first run that rebalancing (redeeming from LP positions) may incur losses due to impermanent loss. The redeemed amount may be less than originally invested.

> Strategy checks every 24 hours.

#### Scheduling Drift Checks via CronCreate (REQUIRED)

After initial allocation completes, the agent **MUST** call `CronCreate` to schedule daily automated drift checks. Do **not** keep the process alive with a blocking loop.

CronCreate parameters:
- **cron**: `"<M> <H> * * *"` — use the current local hour `H` and minute `M`, avoiding `:00` and `:30` marks (offset ±2–3 min if needed)
- **recurring**: `true`
- **durable**: `true` (persists across sessions)
- **prompt**: `"Run risk-parity drift check: cd <absolute-path-to-skill-directory> && python scripts/risk_parity.py --coin <COIN> --mode drift-check <same flags as initial run, excluding --mode>"`

Example prompt for a USDT run launched from `/path/to/skill/risk-parity-allocator`:
```
Run risk-parity drift check: cd /path/to/skill/risk-parity-allocator && python scripts/risk_parity.py --coin USDT --mode drift-check
```

**Important notes:**
- The scheduled task re-runs from scratch each day (fresh APR fetch + weight calculation), which is more accurate than carrying stale weights forward.
- CronCreate jobs auto-expire after **7 days**. Inform the user when scheduling, and re-run the initial setup to renew the job before expiry.
- When the cron fires, the agent executes `--mode drift-check`, which checks drift and rebalances if needed, then exits. No need to create a new CronCreate job — `recurring: true` handles repetition.

## Dual Asset Direction Logic

The direction for Dual Asset products depends on the investment coin:
- **coin = USDT:** Subscribe to BuyLow products (quoteCoin=USDT). If the price drops to strike, you buy the target coin at that price.
- **coin ≠ USDT (e.g., BTC):** Subscribe to SellHigh products (baseCoin=coin). If the price rises to strike, your coin is sold at that price.

Product preference (default: nearest-farthest): select the product with the nearest expiry date and the farthest strike price from current market price.

## Debug Mode

When `--debug` is specified:
- No API key or secret required
- Product APIs are queried normally (for coin support check and APR fetch)
- Outputs: allocation plan with weights, selected products, and full API request bodies as JSON
- No actual POST requests executed
- Generates log file `riskparity_debug_{YYYYMMDD_HHMMSS}.log` recording each step's data and decision logic
- Use `--log-dir` to specify log file output directory (default: current directory)
- Exits after producing the plan (no loop)

## Scripts & Reference

### Reference: `reference/earn-api.md`
Complete API specification for Bybit Earn endpoints (standard/advanced products, positions, place-order, balance query, authentication, rate limits). Covers FlexibleSaving, OnChain, LiquidityMining, DualAssets, and DoubleWin categories.

### Script: `scripts/bybit_client.py`
Bybit API client with HMAC-SHA256 authentication and mandatory headers.
- `BybitClient(env_override=None)` — Initialize client (reads BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_ENV from environment)
- `client.verify_credentials()` — Validate API key/secret, check clock sync
- `client.get(endpoint, params=None)` — Authenticated GET request with rate limiting
- `client.post(endpoint, body=None)` — Authenticated POST request with rate limiting
- `client.confirm_operation(summary)` — Display summary and prompt CONFIRM (auto-confirms on testnet)

### Script: `scripts/risk_parity.py`
Main strategy script for risk-parity allocation across Earn products.
- `get_fund_balance(client, coin)` — Query FUND account balance
- `get_total_capital(client, coin, product_types)` — Calculate total capital (FUND + all positions)
- `get_products_by_type(client, product_type, coin=None)` — Fetch available products by category
- `get_positions_by_type(client, product_type)` — Get current positions by category
- `check_coin_support(client, coin, product_types)` — Verify coin support for each product type
- `get_product_apr(client, product_type, coin)` — Fetch best APR for a product type
- `calculate_weights(type_apr_map, allowed_risk_levels, max_alloc, min_alloc)` — Compute APR/risk-weighted allocation
- `select_dual_asset_product(client, coin, max_days=1)` — Select Dual Asset product (farthest strike, nearest expiry)
- `select_doublewin_product(client)` — Select shortest-expiry DoubleWin product
- `select_best_product(client, product_type, coin)` — Select highest-APR product for a category
- `validate_order_amount(product_type, amount)` — Check against min/max order limits
- `execute_allocation(client, allocations, total_capital, coin)` — Execute subscription orders (refreshes apyE8 before each Dual Asset order)
- `execute_rebalance(client, allocations, total_capital, coin, drift_threshold)` — Drift check and rebalance
- `generate_report(allocations, total_capital, coin)` — Print allocation report

**Run:** `python scripts/risk_parity.py --coin USDT [--capital 10000] [--debug] [--testnet] [--mode initial|drift-check]`

- `--mode initial` (default): full setup + initial subscription; prints CronCreate scheduling instructions on exit
- `--mode drift-check`: recalculates fresh target weights, checks drift, rebalances if needed; designed for scheduled/cron execution

### Agent Execution Guidance

> **IMPORTANT: Script-First Approach**
>
> Before making direct API calls, the agent MUST first check if the required functionality is already implemented in the scripts above.
> - **Preferred:** Execute strategy via `python scripts/risk_parity.py` with appropriate flags (`--debug` for dry-run, `--testnet` for test execution, no flag for mainnet)
> - **Fallback only:** If the scripts do not cover a specific operation (e.g., querying a single balance, checking a specific position, or one-off manual operations), the agent may construct API requests directly using the reference documentation
> - The scripts already handle: authentication, rate limiting, mandatory headers, order confirmation, split orders, error handling, and logging
> - Do NOT re-implement existing script functionality via raw API calls

## API Endpoints

All requests MUST include:
- `User-Agent: bybit-skill/1.3.0`
- `X-Referer: bybit-skill`

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | /v5/earn/product | List standard Earn products |
| GET | /v5/earn/advance/product | List advanced Earn products |
| GET | /v5/earn/advance/product-extra-info | Dual Asset quotes/strikes |
| GET | /v5/earn/position | Current standard positions |
| GET | /v5/earn/advance/position | Current advanced positions |
| POST | /v5/earn/place-order | Subscribe/redeem standard products |
| POST | /v5/earn/advance/place-order | Subscribe/redeem advanced products |
| GET | /v5/asset/transfer/query-account-coins-balance | Check FUND balance |

## Risk Disclaimer

Risk-parity with APR weighting optimizes for risk-adjusted return but does not eliminate risk. **Risk warning**: Risk scores are heuristic assignments, not actuarial calculations. APR is historical and may not predict future returns. DoubleWin can result in total principal loss. Market regime changes can invalidate risk estimates.

## Installation & Usage

```bash
pip install requests

# Live mode (auto-detect capital from account)
python scripts/risk_parity.py --coin USDT

# BTC portfolio allocation
python scripts/risk_parity.py --coin BTC \
  --allowed-types FlexibleSaving,OnChain,DualAssets

# Debug mode (no API key needed, --capital required)
python scripts/risk_parity.py --capital 10000 --coin USDT --debug

# Testnet mode (API key required, auto-detect testnet balance)
python scripts/risk_parity.py --coin USDT --testnet
```

## Confirmation Mechanism

All allocation operations (subscribe/redeem) on Mainnet require explicit confirmation. Type "CONFIRM" to proceed.
