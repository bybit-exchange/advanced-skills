# Bybit Earn API Reference (Risk Parity)

All requests MUST include headers:
```
User-Agent: bybit-skill/1.3.0
X-Referer: bybit-skill
```

## Standard Earn Products

### GET /v5/earn/product

List standard Earn products.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | FlexibleSaving, OnChain, LiquidityMining |
| coin | No | Filter by investment coin (e.g., USDT, BTC) |

**Key response fields:**
- `productId`, `coin`, `apyE8`, `status`, `minPurchaseAmount`, `maxPurchaseAmount`

**Coin Support Check:** Query with `coin` parameter. If response returns Available products, the coin is supported for that category.

### GET /v5/earn/position

Current standard positions.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | FlexibleSaving, OnChain, LiquidityMining |

### POST /v5/earn/place-order

Subscribe/redeem standard products.

**Body (Subscribe):**
```json
{
  "category": "FlexibleSaving",
  "orderType": "Stake",
  "accountType": "FUND",
  "coin": "USDT",
  "amount": "5000",
  "productId": "123",
  "orderLinkId": "rp-flex-abc123"
}
```

**Body (Redeem — Liquidity Mining):**
```json
{
  "category": "LiquidityMining",
  "orderType": "Redeem",
  "accountType": "FUND",
  "coin": "USDT",
  "amount": "1000",
  "productId": "456",
  "orderLinkId": "rp-rdm-abc123"
}
```

**Important:** When redeeming Liquidity Mining positions during rebalance, specify `coin` as the skill's designated allocation coin to receive redemption in that currency.

## Advanced Earn Products

### GET /v5/earn/advance/product

List advanced products.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | DualAssets, DoubleWin |
| coin | No | Filter by coin |

**DualAssets response fields:**
- `productId`, `baseCoin`, `quoteCoin`, `duration`, `status`, `settlementTime`

**DoubleWin response fields:**
- `productId`, `investCoin`, `underlyingAsset`, `duration`, `status`, `settlementTime`

**Note:** DoubleWin only supports USDT as investment coin (`investCoin=USDT`).

### GET /v5/earn/advance/product-extra-info

Get Dual Asset strike prices and quotes.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | DualAssets |
| productId | Yes | Product ID |

**Response:**
- `currentPrice` — Current market price
- `buyLowPrice[]` — BuyLow quotes (selectPrice, apyE8, expiredAt)
- `sellHighPrice[]` — SellHigh quotes (selectPrice, apyE8, expiredAt)

### GET /v5/earn/advance/position

Current advanced positions.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| category | Yes | DualAssets, DoubleWin |

### POST /v5/earn/advance/place-order

Subscribe/redeem advanced products.

**Body (DualAssets — BuyLow, coin=USDT):**
```json
{
  "category": "DualAssets",
  "productId": 81749,
  "orderType": "Stake",
  "amount": "5000",
  "accountType": "FUND",
  "coin": "USDT",
  "orderLinkId": "rp-dual-abc123",
  "dualAssetsExtra": {
    "orderDirection": "BuyLow",
    "selectPrice": "62000",
    "apyE8": 500000000
  }
}
```

**Body (DualAssets — SellHigh, coin=BTC):**
```json
{
  "category": "DualAssets",
  "productId": 81750,
  "orderType": "Stake",
  "amount": "0.5",
  "accountType": "FUND",
  "coin": "BTC",
  "orderLinkId": "rp-dual-def456",
  "dualAssetsExtra": {
    "orderDirection": "SellHigh",
    "selectPrice": "75000",
    "apyE8": 400000000
  }
}
```

**Body (DoubleWin):**
```json
{
  "category": "DoubleWin",
  "productId": 15001,
  "orderType": "Stake",
  "amount": "200",
  "accountType": "FUND",
  "coin": "USDT",
  "orderLinkId": "rp-dbwn-abc123"
}
```

## GET /v5/asset/transfer/query-account-coins-balance

Check FUND account balance.

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| accountType | Yes | `FUND` |
| coin | No | Filter by coin (e.g., USDT) |

**Response:**
```json
{
  "retCode": 0,
  "result": {
    "accountType": "FUND",
    "balance": [
      {
        "coin": "USDT",
        "transferBalance": "25000.0",
        "walletBalance": "25000.0"
      }
    ]
  }
}
```

## Dual Asset Direction Logic

| Investment Coin | Direction | Product Filter | Strike Selection |
|----------------|-----------|---------------|-----------------|
| USDT | BuyLow | quoteCoin = USDT | Lowest strike (farthest below spot) |
| Non-USDT (BTC, ETH) | SellHigh | baseCoin = coin | Highest strike (farthest above spot) |

**Product Selection Preference (nearest-farthest):**
1. Sort products by `settlementTime` ascending (nearest expiry first)
2. For the nearest product, select the strike farthest from current price

## Order Amount Limits

| Product Type | Minimum | Maximum |
|-------------|---------|---------|
| FlexibleSaving | None | None |
| OnChain | 50 USD | 200,000 USD |
| LiquidityMining | 100 USD | None |
| DualAssets | 50 USD | 200,000 USD |
| DoubleWin | 50 USD | 1,000 USD |

- Below minimum: skip the allocation (do not place order)
- Above maximum: cap at the maximum amount

## Risk Score & Weight Formula

| Product Type | Category | Risk Score |
|-------------|----------|------------|
| Flexible Savings | FlexibleSaving | 1 |
| On-Chain Earn | OnChain | 2 |
| Liquidity Mining | LiquidityMining | 3 |
| Dual Assets | DualAssets | 4 |
| DoubleWin | DoubleWin | 5 |

**Weight Formula (APR/risk):**
```
weight_i = (APR_i / risk_i) / Σ(APR_j / risk_j)
```

**DoubleWin special:** Fixed 5% allocation, does not participate in APR/risk calculation.

Example with FlexibleSaving(APR=5%, risk=1), OnChain(APR=8%, risk=2), DualAssets(APR=12%, risk=4):
- Scores: 5/1=5.0, 8/2=4.0, 12/4=3.0
- Sum = 12.0
- Weights (of remaining 95%): 39.6%, 31.7%, 23.7%
- Plus DoubleWin: 5%

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

- GET: minimum 100ms interval
- POST: minimum 300ms interval
- On retCode=10006: wait 500-1500ms, retry max 3 times
