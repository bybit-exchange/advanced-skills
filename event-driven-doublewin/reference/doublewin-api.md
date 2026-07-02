# Bybit DoubleWin & Account API Reference

All requests MUST include headers:
```
User-Agent: bybit-skill/1.3.0
X-Referer: bybit-skill
```

## GET /v5/earn/advance/product?category=DoubleWin

List available DoubleWin products.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | Must be `DoubleWin` |
| coin | No | Filter by underlying asset (e.g., BTC) |

**Response fields:**
- `productId` — Unique product ID
- `investCoin` — Investment coin (USDT)
- `underlyingAsset` — Underlying asset (BTC, ETH)
- `duration` — Product duration in hours
- `status` — Available / SoldOut
- `isRfqProduct` — Whether RFQ-based (true/false)
- `minPurchaseAmount` — Minimum investment amount
- `remainingAmount` — Remaining subscription capacity
- `orderPrecisionDigital` — Amount decimal precision
- `subscribeStartAt` — Subscription open timestamp (ms)
- `subscribeEndAt` — Subscription close timestamp (ms)
- `settlementTime` — Settlement timestamp (ms)

**Settlement Time Usage:**
- Products must be selected where `settlementTime > event_time_ms` (ensures product covers the event's volatility window)
- After successful order, record `settlementTime` to prevent duplicate orders until settlement

## GET /v5/earn/advance/product-extra-info?category=DoubleWin

Get leverage options and pricing details.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | Must be `DoubleWin` |
| productId | Yes | Product ID from product list |

**Response (fixed-range products, isRfqProduct=false):**
- `leverage[]` — Array of leverage options:
  - `multiplier` — Leverage multiplier (e.g., "2", "5", "10")
  - `cost` — Cost/premium for this leverage level
  - `upperBuffer` — Upper price buffer percentage
  - `lowerBuffer` — Lower price buffer percentage
- `currentPrice` — Current market price
- `expireTime` — Quote expiration

**Note:** RFQ products (`isRfqProduct=true`) use WebSocket `earn.doublewin.offers` for real-time quotes.

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
        "transferBalance": "5000.0",
        "walletBalance": "5000.0",
        "bonus": "0"
      }
    ]
  }
}
```

**Key field:** `transferBalance` — available balance for orders.

**Usage:** Before each trade, verify `transferBalance` >= `capitalPerTrade`. If insufficient, skip the round.

## POST /v5/earn/advance/place-order (DoubleWin)

Subscribe to a DoubleWin product.

**Body:**
```json
{
  "category": "DoubleWin",
  "productId": 15001,
  "orderType": "Stake",
  "amount": "200",
  "accountType": "FUND",
  "coin": "USDT",
  "orderLinkId": "dw-abc123def456",
  "doubleWinExtra": {
    "leverage": "5"
  }
}
```

**Required fields:**
- `category`: Must be `DoubleWin`
- `productId`: Integer product ID
- `orderType`: Must be `Stake`
- `amount`: Investment amount in USDT (max 1000)
- `accountType`: Must be `FUND` (funding account)
- `coin`: Must be `USDT`
- `orderLinkId`: Unique identifier (recommended format: `dw-{uuid}`)
- `doubleWinExtra.leverage`: Leverage multiplier as string

## GET /v5/earn/advance/position?category=DoubleWin

Monitor DoubleWin positions.

**Response fields:**
- `productId` — Product ID
- `amount` — Invested amount
- `leverage` — Selected leverage
- `status` — Pending / Settled
- `settlementTime` — When it settles (ms timestamp)
- `pnl` — Profit/Loss amount

## GET /v5/earn/advance/order?category=DoubleWin

Query order history and settlements.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | `DoubleWin` |
| orderId | No | Specific order ID |
| startTime | No | Start timestamp (ms) |
| endTime | No | End timestamp (ms) |
| limit | No | 1-20, default 20 |

**Response includes:**
- `status` — Order status (Pending, Settled)
- `settlementResult` — Win / Lose
- `pnlAmount` — Settlement P&L amount

## Product Selection Rule

When selecting a DoubleWin product for an event-driven trade:

1. Filter products where `status == "Available"`
2. Filter products where `settlementTime > event_time_ms` (product must settle AFTER the event)
3. Among valid products, select the one with the closest settlement time after the event (shortest duration that still covers the event)

This ensures the product's observation window encompasses the expected volatility around the event.

## DoubleWin Mechanics

- Profits from large price movements in **EITHER direction**
- If price moves beyond upper buffer OR below lower buffer at settlement → **Profit**
- If price stays within buffer zone → **Loss** (partial or full principal)
- Higher leverage = smaller buffer = more likely to profit, but higher cost
- Maximum investment per order: 1000 USDT

## Authentication

| Header | Value |
|--------|-------|
| X-BAPI-API-KEY | API Key |
| X-BAPI-TIMESTAMP | Unix ms timestamp |
| X-BAPI-SIGN | HMAC-SHA256 signature |
| X-BAPI-RECV-WINDOW | 5000 |
| User-Agent | bybit-skill/1.3.0 |
| X-Referer | bybit-skill |

## Rate Limits

- GET (product list): 50/s, minimum 100ms interval
- GET (position/order): 10/s, minimum 100ms interval
- POST (place-order): 5/s, minimum 300ms interval
