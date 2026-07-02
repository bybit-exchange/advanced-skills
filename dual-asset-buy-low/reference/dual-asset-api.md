# Bybit Dual Asset API Reference

All requests MUST include headers:
```
User-Agent: bybit-skill/1.3.0
X-Referer: bybit-skill
```

## GET /v5/earn/advance/product?category=DualAssets

List available Dual Asset products.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | Must be `DualAssets` |
| coin | No | Filter by base coin (e.g., BTC) |

**Response fields:**
- `productId` — Unique product ID
- `baseCoin` — Base coin (e.g., BTC)
- `quoteCoin` — Quote coin (e.g., USDT)
- `duration` — Lock period in days
- `status` — Available / SoldOut
- `subscribeStartAt` / `subscribeEndAt` — Subscription window
- `settlementTime` — Settlement timestamp (ms)
- `minPurchaseQuoteAmount` — Min quote coin for BuyLow
- `minPurchaseBaseAmount` — Min base coin for SellHigh
- `remainingAmountQuote` / `remainingAmountBase` — Remaining capacity
- `orderPrecisionDigitalQuote` / `orderPrecisionDigitalBase` — Amount precision

**Product Filtering:**
When selecting products for BuyLow orders, filter by both `baseCoin` (target coin to accumulate) and `quoteCoin` (user's investment coin). Example: to buy BTC with USDT, filter `baseCoin=BTC` AND `quoteCoin=USDT`.

## GET /v5/earn/advance/product-extra-info?category=DualAssets

Get strike prices and premium quotes.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | Must be `DualAssets` |
| productId | Yes | Product ID from product list |

**Response fields:**
- `currentPrice` — Current market price
- `buyLowPrice[]` — Array of BuyLow quotes:
  - `selectPrice` — Strike price (this IS the effective buy price)
  - `apyE8` — Premium APY in E8 format
  - `maxInvestmentAmount` — Max investment for this strike
  - `expiredAt` — Quote expiration timestamp
- `sellHighPrice[]` — Array of SellHigh quotes (same structure)

**Important:** Only use quotes where `expiredAt` > current time.

**Effective Buy Price:** The effective buy price equals the strike price (`selectPrice`) directly. No premium subtraction needed.

## GET /v5/asset/transfer/query-account-coins-balance

Check FUND account balance before placing orders.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| accountType | Yes | `FUND` |
| coin | No | Filter by specific coin (e.g., USDT) |

**Response:**
```json
{
  "retCode": 0,
  "result": {
    "accountType": "FUND",
    "balance": [
      {
        "coin": "USDT",
        "transferBalance": "15000.5",
        "walletBalance": "15000.5",
        "bonus": "0"
      }
    ]
  }
}
```

**Key field:** `transferBalance` — available balance that can be used for orders.

**Usage:** Before each round, verify `transferBalance` >= `investPerRound`. If insufficient, skip the round.

## POST /v5/earn/advance/place-order

Subscribe to a Dual Asset product.

**Body:**
```json
{
  "category": "DualAssets",
  "productId": 81749,
  "orderType": "Stake",
  "amount": "500",
  "accountType": "FUND",
  "coin": "USDT",
  "orderLinkId": "buylow-abc123def456",
  "dualAssetsExtra": {
    "orderDirection": "BuyLow",
    "selectPrice": "69500",
    "apyE8": 855000000
  }
}
```

**Required fields:** All 8 parameters are mandatory.
- `accountType`: Must be `FUND` (uses funding account assets)
- `coin`: The quote coin being invested (e.g., USDT, USDC)
- `orderDirection`: `BuyLow` (invest quote coin, buy base coin if price drops)
- `selectPrice`: Must match a valid, non-expired quote
- `apyE8`: Must match the quote for the selected strike price
- `orderLinkId`: Unique identifier for the order

**Split Order Handling:**
When `investPerRound` exceeds the product's `maxInvestmentAmount`, orders must be split:
- Each sub-order `amount` ≤ `maxInvestmentAmount * 80%`
- Before each sub-order, re-query `GET /v5/earn/advance/product-extra-info` to get the latest `maxInvestmentAmount` for the selected strike
- Wait 5 seconds between sub-orders
- Re-check conditions before each sub-order: `selectPrice ≤ targetBuyPrice` AND `apyE8/1e8 ≥ minPremiumYield`
- If conditions fail or `maxInvestmentAmount` unavailable, stop remaining sub-orders

## GET /v5/earn/advance/position?category=DualAssets

Monitor Dual Asset positions.

**Response fields:**
- `productId` — Product ID
- `coin` — Invested coin
- `amount` — Invested amount
- `status` — Pending / Settled
- `settlementTime` — When it settles (ms timestamp)
- `direction` — BuyLow / SellHigh

**Settlement Time Tracking:**
After successful order placement, record `settlementTime` from the product data. Do not place new orders until the current time exceeds this settlement time (prevents duplicate subscriptions during the lock period).

## Authentication

| Header | Value |
|--------|-------|
| X-BAPI-API-KEY | API Key |
| X-BAPI-TIMESTAMP | Unix ms timestamp |
| X-BAPI-SIGN | HMAC-SHA256 signature |
| X-BAPI-RECV-WINDOW | 5000 |
| User-Agent | bybit-skill/1.3.0 |
| X-Referer | bybit-skill |

## APY Conversion

`apyE8` fields use E8 format: divide by 10^8 to get decimal, multiply by 100 for percentage.
Example: `855000000` → 8.55%

## Rate Limits

- GET requests: minimum 100ms interval
- POST requests: minimum 300ms interval
- Balance query: same as GET limits
