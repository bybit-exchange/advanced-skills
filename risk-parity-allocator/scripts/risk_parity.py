"""
Risk-Parity Earn Allocator — APR/risk weighted allocation across Earn products.
All API requests include: User-Agent: bybit-skill/1.3.0, X-Referer: bybit-skill
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from bybit_client import BybitClient

RISK_SCORES = {
    "FlexibleSaving": 1,
    "OnChain": 2,
    "LiquidityMining": 3,
    "DualAssets": 4,
    "DoubleWin": 5,
}

ORDER_LIMITS = {
    "FlexibleSaving": {"min": 0, "max": float("inf")},
    "OnChain": {"min": 50, "max": 200000},
    "LiquidityMining": {"min": 100, "max": float("inf")},
    "DualAssets": {"min": 50, "max": 200000},
    "DoubleWin": {"min": 50, "max": 1000},
}

DOUBLEWIN_FIXED_WEIGHT = 0.05
DUALASSETS_MAX_WEIGHT = 0.20


class DebugLogger:
    def __init__(self, enabled=False, log_dir=None):
        self.enabled = enabled
        self.file = None
        if enabled:
            log_dir = log_dir or os.getcwd()
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(log_dir, f"riskparity_debug_{timestamp}.log")
            self.file = open(filepath, "w", encoding="utf-8")
            self.log(f"Risk-Parity Debug Log — {datetime.now().isoformat()}")
            self.log(f"Log file: {filepath}")
            print(f"  [DEBUG] Log file: {filepath}")

    def log(self, message):
        if self.enabled and self.file:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.file.write(f"[{ts}] {message}\n")
            self.file.flush()

    def close(self):
        if self.file:
            self.file.close()


def _format_amount(value):
    if float(value) == int(float(value)):
        return str(int(float(value)))
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


def get_fund_balance(client, coin, logger=None):
    resp = client.get("/v5/asset/transfer/query-account-coins-balance", {
        "accountType": "FUND",
        "coin": coin,
    })
    if not resp or resp.get("retCode") != 0:
        print(f"  Failed to query FUND balance: {resp}")
        if logger:
            logger.log(f"FUND balance query FAILED: {resp}")
        return 0.0
    coins = resp["result"].get("balance", [])
    for c in coins:
        if c.get("coin") == coin:
            balance = float(c.get("transferBalance", "0"))
            if logger:
                logger.log(f"FUND balance: {balance} {coin}")
            return balance
    if logger:
        logger.log(f"FUND balance: 0.0 {coin} (coin not found)")
    return 0.0


def get_all_positions_amount(client, coin, product_types):
    total = 0.0
    details = {}
    for ptype in product_types:
        positions = get_positions_by_type(client, ptype)
        ptype_amount = 0.0
        for p in positions:
            pos_coin = p.get("coin", p.get("investCoin", ""))
            if pos_coin and pos_coin != coin:
                continue
            amt = float(p.get("amount", p.get("investAmount", "0")))
            ptype_amount += amt
        if ptype_amount > 0:
            details[ptype] = ptype_amount
            total += ptype_amount
    return total, details


def get_total_capital(client, coin, product_types, logger=None):
    fund_balance = get_fund_balance(client, coin, logger)
    positions_total, positions_detail = get_all_positions_amount(client, coin, product_types)
    total = fund_balance + positions_total
    print(f"\n  Capital Breakdown:")
    print(f"    FUND balance: {fund_balance:.2f} {coin}")
    if positions_detail:
        for ptype, amt in positions_detail.items():
            print(f"    {ptype} positions: {amt:.2f} {coin}")
    print(f"    Total capital: {total:.2f} {coin}")
    if logger:
        logger.log(f"Capital breakdown: FUND={fund_balance}, positions={positions_detail}, total={total}")
    return total, fund_balance, positions_detail


def get_products_by_type(client, product_type, coin=None):
    params = {"category": product_type}
    if coin and product_type not in ("DualAssets",):
        params["coin"] = coin

    if product_type in ("FlexibleSaving", "OnChain", "LiquidityMining"):
        resp = client.get("/v5/earn/product", params)
    else:
        resp = client.get("/v5/earn/advance/product", params)

    if not resp or resp.get("retCode") != 0:
        return []
    products = resp["result"].get("list", [])
    now_ms = int(time.time() * 1000)
    filtered = []
    for p in products:
        if p.get("status") == "Available":
            filtered.append(p)
        elif product_type == "DoubleWin" and int(p.get("subscribeEndAt", "0")) > now_ms and not p.get("isRfqProduct", False):
            filtered.append(p)
    return filtered


def get_positions_by_type(client, product_type):
    if product_type in ("FlexibleSaving", "OnChain", "LiquidityMining"):
        resp = client.get("/v5/earn/position", {"category": product_type})
    else:
        resp = client.get("/v5/earn/advance/position", {"category": product_type})

    if not resp or resp.get("retCode") != 0:
        return []
    return resp["result"].get("list", [])


def check_coin_support(client, coin, product_types, debug=False, logger=None):
    support = {}
    for ptype in product_types:
        if ptype == "DoubleWin":
            support[ptype] = (coin == "USDT")
            if logger:
                logger.log(f"Coin support check: {ptype} — {'supported' if coin == 'USDT' else 'NOT supported'} (USDT only)")
            continue

        if ptype == "DualAssets":
            products = get_products_by_type(client, "DualAssets")
            if coin == "USDT":
                has_products = any(p.get("quoteCoin") == "USDT" for p in products)
            else:
                has_products = any(p.get("baseCoin") == coin for p in products)
            support[ptype] = has_products
            if logger:
                logger.log(f"Coin support check: {ptype} — {'supported' if has_products else 'NOT supported'} ({len(products)} products found)")
            continue

        products = get_products_by_type(client, ptype, coin=coin)
        support[ptype] = len(products) > 0
        if logger:
            logger.log(f"Coin support check: {ptype} — {'supported' if len(products) > 0 else 'NOT supported'} ({len(products)} products)")

    return support


def get_product_apr(client, product_type, coin, logger=None):
    if product_type == "DoubleWin":
        if logger:
            logger.log(f"APR fetch: {product_type} — 0.0 (no APR for DoubleWin)")
        return 0.0

    if product_type == "DualAssets":
        products = get_products_by_type(client, "DualAssets")
        if coin == "USDT":
            products = [p for p in products if p.get("quoteCoin") == "USDT"]
        else:
            products = [p for p in products if p.get("baseCoin") == coin]
        if not products:
            if logger:
                logger.log(f"APR fetch: DualAssets — 0.0 (no products for {coin})")
            return 0.0
        product = products[0]
        resp = client.get("/v5/earn/advance/product-extra-info", {
            "category": "DualAssets",
            "productId": str(product.get("productId")),
        })
        if not resp or resp.get("retCode") != 0:
            if logger:
                logger.log(f"APR fetch: DualAssets — 0.0 (extra-info query failed)")
            return 0.0
        result = resp["result"]
        items = result.get("list", [])
        if items:
            result = items[0]
        price_key = "buyLowPrice" if coin == "USDT" else "sellHighPrice"
        quotes = result.get(price_key, [])
        now_ms = int(time.time() * 1000)
        valid_quotes = [q for q in quotes if int(q.get("expiredAt", "0")) > now_ms]
        if valid_quotes:
            best_apy = max(int(q.get("apyE8", "0")) for q in valid_quotes)
            apr_result = best_apy / 1e8
            if logger:
                logger.log(f"APR fetch: DualAssets — {apr_result*100:.2f}% (from {len(valid_quotes)} valid quotes)")
            return apr_result
        if logger:
            logger.log(f"APR fetch: DualAssets — 0.0 (no valid quotes)")
        return 0.0

    products = get_products_by_type(client, product_type, coin=coin)
    if not products:
        if logger:
            logger.log(f"APR fetch: {product_type} — 0.0 (no products)")
        return 0.0
    best_apy = 0.0
    for p in products:
        estimate_apr = p.get("estimateApr", "")
        if estimate_apr:
            apr_val = float(estimate_apr.replace("%", "")) / 100.0
            if apr_val > best_apy:
                best_apy = apr_val
            continue
        apy_e8 = int(p.get("apyE8", "0") or "0")
        apy = apy_e8 / 1e8 if apy_e8 > 100 else float(p.get("apy", "0") or "0")
        if apy > best_apy:
            best_apy = apy
    if logger:
        logger.log(f"APR fetch: {product_type} — {best_apy*100:.2f}% (from {len(products)} products)")
    return best_apy


def _risk_adjusted_score(ptype, raw_apr, risk):
    import math
    ratio = raw_apr / risk
    if ptype == "DualAssets" and ratio > 0:
        return math.log10(ratio) if ratio >= 1 else ratio
    return ratio


def calculate_weights(type_apr_map, allowed_risk_levels, max_alloc, min_alloc, logger=None):
    allocations = []

    doublewin_weight = 0.0
    if "DoubleWin" in type_apr_map and 5 in allowed_risk_levels:
        doublewin_weight = DOUBLEWIN_FIXED_WEIGHT
        allocations.append({"type": "DoubleWin", "risk": 5, "weight": doublewin_weight, "apr": 0.0})

    remaining_budget = 1.0 - doublewin_weight
    eligible = []
    for ptype, apr in type_apr_map.items():
        if ptype == "DoubleWin":
            continue
        risk = RISK_SCORES.get(ptype, 3)
        if risk not in allowed_risk_levels:
            continue
        if apr <= 0:
            continue
        score = _risk_adjusted_score(ptype, apr, risk)
        eligible.append({"type": ptype, "risk": risk, "apr": apr, "score": score})

    if not eligible:
        if allocations:
            allocations[0]["weight"] = 1.0
        return allocations

    total_score = sum(e["score"] for e in eligible)
    if total_score <= 0:
        equal_w = remaining_budget / len(eligible)
        for e in eligible:
            e["weight"] = equal_w
    else:
        for e in eligible:
            e["weight"] = e["score"] / total_score * remaining_budget

    for e in eligible:
        type_max = DUALASSETS_MAX_WEIGHT if e["type"] == "DualAssets" else max_alloc
        e["weight"] = max(min_alloc, min(type_max, e["weight"]))

    total_w = sum(e["weight"] for e in eligible)
    if total_w > 0:
        for e in eligible:
            e["weight"] = e["weight"] / total_w * remaining_budget

    dual_over = False
    for e in eligible:
        if e["type"] == "DualAssets" and e["weight"] > DUALASSETS_MAX_WEIGHT:
            excess = e["weight"] - DUALASSETS_MAX_WEIGHT
            e["weight"] = DUALASSETS_MAX_WEIGHT
            dual_over = True

    if dual_over:
        non_dual = [e for e in eligible if e["type"] != "DualAssets"]
        non_dual_total = sum(e["weight"] for e in non_dual)
        redistributed_budget = remaining_budget - DUALASSETS_MAX_WEIGHT
        if non_dual_total > 0:
            for e in non_dual:
                e["weight"] = e["weight"] / non_dual_total * redistributed_budget

    for e in eligible:
        if "score" in e:
            del e["score"]

    allocations.extend(eligible)
    if logger:
        for a in allocations:
            logger.log(f"Weight result: {a['type']} — risk={a['risk']}, weight={a['weight']*100:.2f}%")
    return allocations


MIN_DUAL_ASSET_APR = 0.15


def select_dual_asset_product(client, coin, max_days=1, pref="nearest-farthest", logger=None):
    products = get_products_by_type(client, "DualAssets")

    if coin == "USDT":
        filtered = [p for p in products if p.get("quoteCoin") == "USDT"]
        direction = "BuyLow"
    else:
        filtered = [p for p in products if p.get("baseCoin") == coin]
        direction = "SellHigh"

    if not filtered:
        return None, None, None

    now_ms = int(time.time() * 1000)
    max_settlement_ms = now_ms + int(max_days * 24 * 3600 * 1000)
    filtered = [p for p in filtered if int(p.get("settlementTime", "0")) <= max_settlement_ms]

    if not filtered:
        return None, None, None

    # Sort by settlement time ascending (nearest expiry first, per SKILL.md Step 6)
    filtered.sort(key=lambda p: int(p.get("settlementTime", "0")))

    for product in filtered:
        resp = client.get("/v5/earn/advance/product-extra-info", {
            "category": "DualAssets",
            "productId": str(product.get("productId")),
        })
        if not resp or resp.get("retCode") != 0:
            continue

        result = resp["result"]
        items = result.get("list", [])
        if items:
            result = items[0]

        price_key = "buyLowPrice" if direction == "BuyLow" else "sellHighPrice"
        quotes = result.get(price_key, [])
        current_price = float(result.get("currentPrice", "0"))

        best_quote = None
        best_distance = -1
        for q in quotes:
            if int(q.get("expiredAt", "0")) <= now_ms:
                continue
            apy = int(q.get("apyE8", "0")) / 1e8
            if apy < MIN_DUAL_ASSET_APR:
                continue
            strike = float(q.get("selectPrice", "0"))
            distance = abs(current_price - strike)
            if distance > best_distance:
                best_distance = distance
                best_quote = q

        if best_quote is not None:
            strike = float(best_quote.get("selectPrice", "0"))
            apy = int(best_quote.get("apyE8", "0")) / 1e8
            if logger:
                logger.log(f"DualAsset selection: {direction} productId={product.get('productId')}, "
                           f"strike={strike}, APY={apy*100:.2f}%, distance={best_distance:.2f}")
            return product, direction, best_quote

    if logger:
        logger.log(f"DualAsset selection: no valid candidates (coin={coin}, max_days={max_days})")
    return None, None, None


def select_doublewin_product(client):
    products = get_products_by_type(client, "DoubleWin")
    if not products:
        return None
    now_ms = int(time.time() * 1000)
    subscribable = [
        p for p in products
        if not p.get("isRfqProduct")
        and int(p.get("subscribeStartAt", "0")) <= now_ms <= int(p.get("subscribeEndAt", "0"))
    ]
    if not subscribable:
        subscribable = [p for p in products if not p.get("isRfqProduct")]
    if not subscribable:
        subscribable = products
    subscribable.sort(key=lambda p: int(p.get("settlementTime", "0")))
    return subscribable[0]


def select_best_product(client, product_type, coin, logger=None):
    products = get_products_by_type(client, product_type, coin=coin)
    if not products:
        if logger:
            logger.log(f"Product selection: {product_type} — no products available")
        return None, 0.0
    best = None
    best_apy = 0.0
    for p in products:
        estimate_apr = p.get("estimateApr", "")
        if estimate_apr:
            apy = float(estimate_apr.replace("%", "")) / 100.0
        else:
            apy_e8 = int(p.get("apyE8", "0") or "0")
            apy = apy_e8 / 1e8 if apy_e8 > 100 else float(p.get("apy", "0") or "0")
        if apy > best_apy:
            best_apy = apy
            best = p
    if logger:
        logger.log(f"Product selection: {product_type} — productId={best.get('productId')}, APY={best_apy*100:.2f}%")
    return best, best_apy


def validate_order_amount(product_type, amount):
    limits = ORDER_LIMITS.get(product_type, {"min": 0, "max": float("inf")})
    if amount < limits["min"]:
        return False, f"below minimum ({limits['min']})"
    capped = min(amount, limits["max"])
    return True, capped


def execute_allocation(client, allocations, total_capital, coin, debug=False, dual_asset_max_days=1, logger=None):
    print("\n  Risk-Parity Allocation Plan:")
    print(f"  {'Type':<20} {'Risk':<6} {'Weight':<8} {'Amount':<12} {'Product':<12} {'Info'}")
    print(f"  {'-'*80}")

    for alloc in allocations:
        ptype = alloc["type"]
        weight = alloc["weight"]
        amount = total_capital * weight

        valid, result = validate_order_amount(ptype, amount)
        if not valid:
            print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'SKIP':<12} {result}")
            continue
        amount = result if isinstance(result, float) else amount

        if ptype == "DualAssets":
            product, direction, quote = select_dual_asset_product(client, coin, max_days=dual_asset_max_days, logger=logger)
            if not product or not quote:
                print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            strike = quote.get("selectPrice", "")

            fresh_resp = client.get("/v5/earn/advance/product-extra-info", {
                "category": "DualAssets",
                "productId": str(product_id),
            })
            apy_e8 = 0
            if fresh_resp and fresh_resp.get("retCode") == 0:
                fresh_result = fresh_resp["result"]
                fresh_items = fresh_result.get("list", [])
                if fresh_items:
                    fresh_result = fresh_items[0]
                price_key = "buyLowPrice" if direction == "BuyLow" else "sellHighPrice"
                fresh_quotes = fresh_result.get(price_key, [])
                now_ms = int(time.time() * 1000)
                strike_str = str(strike)
                matched = False
                for fq in fresh_quotes:
                    if str(fq.get("selectPrice", "")) == strike_str and int(fq.get("expiredAt", "0")) > now_ms:
                        apy_e8 = int(fq.get("apyE8", "0"))
                        matched = True
                        break
                if not matched:
                    print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'SKIP':<12} Fresh quote expired for strike {strike}")
                    if logger:
                        logger.log(f"DualAssets order SKIPPED: fresh quote expired for strike {strike}")
                    continue
            else:
                print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'SKIP':<12} Failed to refresh quote")
                if logger:
                    logger.log(f"DualAssets order SKIPPED: failed to refresh product-extra-info")
                continue

            print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {product_id:<12} "
                  f"{direction} strike={strike} APY={apy_e8/1e8*100:.2f}%")

            body = {
                "category": "DualAssets",
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "accountType": "FUND",
                "coin": coin,
                "orderLinkId": f"rp-dual-{uuid.uuid4().hex[:12]}",
                "dualAssetsExtra": {
                    "orderDirection": direction,
                    "selectPrice": strike,
                    "apyE8": apy_e8,
                },
            }

        elif ptype == "DoubleWin":
            product = select_doublewin_product(client)
            if not product:
                print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            details = client.get("/v5/earn/advance/product-extra-info", {
                "category": "DoubleWin",
                "productId": str(product_id),
            })
            leverage_val = "2"
            initial_price = "0"
            if details and details.get("retCode") == 0:
                result = details["result"]
                items = result.get("list", [])
                if items:
                    result = items[0]
                lev_raw = result.get("leverage", "2")
                if isinstance(lev_raw, list):
                    leverage_val = str(lev_raw[0].get("multiplier", "2"))
                else:
                    leverage_val = str(lev_raw)
                initial_price = str(result.get("currentPrice", "0"))

            print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {product_id:<12} DoubleWin leverage={leverage_val}x")

            body = {
                "category": "DoubleWin",
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "accountType": "FUND",
                "coin": "USDT",
                "orderLinkId": f"rp-dbwn-{uuid.uuid4().hex[:12]}",
                "doubleWinStakeExtra": {
                    "leverage": leverage_val,
                    "initialPrice": initial_price,
                },
            }

        else:
            product, apy = select_best_product(client, ptype, coin, logger=logger)
            if not product:
                print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            print(f"  {ptype:<20} {alloc['risk']:<6} {weight*100:<7.1f}% {amount:<12.0f} {product_id:<12} APY={apy*100:.2f}%")

            body = {
                "category": ptype,
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "coin": coin,
                "accountType": "FUND",
                "orderLinkId": f"rp-{ptype[:4]}-{uuid.uuid4().hex[:12]}",
            }

        if debug:
            print(f"    [DEBUG] Request body:")
            print(f"    {json.dumps(body, indent=2)}")
            if logger:
                logger.log(f"Allocation: {ptype} amount={amount:.2f}, body={json.dumps(body)}")
            continue

        summary = {
            "Action": "Subscribe (Risk-Parity)",
            "Product Type": ptype,
            "Product ID": str(body.get("productId", "")),
            "Amount": f"{int(amount)} {coin}",
            "Risk Score": f"{alloc['risk']}/5",
            "Weight": f"{weight*100:.1f}%",
        }

        if not client.confirm_operation(summary):
            print(f"    -> Skipped by user")
            continue

        is_advance = ptype not in ("FlexibleSaving", "OnChain", "LiquidityMining")
        endpoint = "/v5/earn/advance/place-order" if is_advance else "/v5/earn/place-order"

        resp = client.post(endpoint, body)
        if resp and resp.get("retCode") == 0:
            print(f"    -> Subscribed successfully")
        else:
            print(f"    -> Failed: {resp}")


def execute_allocation_incremental(client, sub_allocations, coin, debug=False, dual_asset_max_days=1, logger=None):
    print("\n  Executing incremental allocation (subscribe only for under-allocated):")
    print(f"  {'Type':<20} {'Amount':<12} {'Product':<12} {'Info'}")
    print(f"  {'-'*70}")

    for alloc in sub_allocations:
        ptype = alloc["type"]
        amount = alloc["_subscribe_amount"]

        valid, result = validate_order_amount(ptype, amount)
        if not valid:
            print(f"  {ptype:<20} {amount:<12.0f} {'SKIP':<12} {result}")
            continue
        amount = result if isinstance(result, float) else amount

        if ptype == "DualAssets":
            product, direction, quote = select_dual_asset_product(client, coin, max_days=dual_asset_max_days)
            if not product or not quote:
                print(f"  {ptype:<20} {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            strike = quote.get("selectPrice", "")

            fresh_resp = client.get("/v5/earn/advance/product-extra-info", {
                "category": "DualAssets",
                "productId": str(product_id),
            })
            apy_e8 = 0
            if fresh_resp and fresh_resp.get("retCode") == 0:
                fresh_result = fresh_resp["result"]
                fresh_items = fresh_result.get("list", [])
                if fresh_items:
                    fresh_result = fresh_items[0]
                price_key = "buyLowPrice" if direction == "BuyLow" else "sellHighPrice"
                fresh_quotes = fresh_result.get(price_key, [])
                now_ms = int(time.time() * 1000)
                strike_str = str(strike)
                matched = False
                for fq in fresh_quotes:
                    if str(fq.get("selectPrice", "")) == strike_str and int(fq.get("expiredAt", "0")) > now_ms:
                        apy_e8 = int(fq.get("apyE8", "0"))
                        matched = True
                        break
                if not matched:
                    print(f"  {ptype:<20} {amount:<12.0f} {'SKIP':<12} Fresh quote expired for strike {strike}")
                    continue
            else:
                print(f"  {ptype:<20} {amount:<12.0f} {'SKIP':<12} Failed to refresh quote")
                continue

            print(f"  {ptype:<20} {amount:<12.0f} {product_id:<12} "
                  f"{direction} strike={strike} APY={apy_e8/1e8*100:.2f}%")

            body = {
                "category": "DualAssets",
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "accountType": "FUND",
                "coin": coin,
                "orderLinkId": f"rp-dual-{uuid.uuid4().hex[:12]}",
                "dualAssetsExtra": {
                    "orderDirection": direction,
                    "selectPrice": strike,
                    "apyE8": apy_e8,
                },
            }

        elif ptype == "DoubleWin":
            product = select_doublewin_product(client)
            if not product:
                print(f"  {ptype:<20} {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            details = client.get("/v5/earn/advance/product-extra-info", {
                "category": "DoubleWin",
                "productId": str(product_id),
            })
            leverage_val = "2"
            initial_price = "0"
            if details and details.get("retCode") == 0:
                res = details["result"]
                items = res.get("list", [])
                if items:
                    res = items[0]
                lev_raw = res.get("leverage", "2")
                if isinstance(lev_raw, list):
                    leverage_val = str(lev_raw[0].get("multiplier", "2"))
                else:
                    leverage_val = str(lev_raw)
                initial_price = str(res.get("currentPrice", "0"))

            print(f"  {ptype:<20} {amount:<12.0f} {product_id:<12} DoubleWin leverage={leverage_val}x")

            body = {
                "category": "DoubleWin",
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "accountType": "FUND",
                "coin": "USDT",
                "orderLinkId": f"rp-dbwn-{uuid.uuid4().hex[:12]}",
                "doubleWinStakeExtra": {
                    "leverage": leverage_val,
                    "initialPrice": initial_price,
                },
            }

        else:
            product, apy = select_best_product(client, ptype, coin)
            if not product:
                print(f"  {ptype:<20} {amount:<12.0f} {'N/A':<12} No product")
                continue

            product_id = product.get("productId", "")
            print(f"  {ptype:<20} {amount:<12.0f} {product_id:<12} APY={apy*100:.2f}%")

            body = {
                "category": ptype,
                "productId": str(product_id),
                "orderType": "Stake",
                "amount": _format_amount(amount),
                "coin": coin,
                "accountType": "FUND",
                "orderLinkId": f"rp-{ptype[:4]}-{uuid.uuid4().hex[:12]}",
            }

        if debug:
            print(f"    [DEBUG] Request body:")
            print(f"    {json.dumps(body, indent=2)}")
            continue

        summary = {
            "Action": "Subscribe (Risk-Parity)",
            "Product Type": ptype,
            "Product ID": str(body.get("productId", "")),
            "Amount": f"{_format_amount(amount)} {coin}",
            "Risk Score": f"{alloc['risk']}/5",
            "Weight": f"{alloc['weight']*100:.1f}%",
        }

        if not client.confirm_operation(summary):
            print(f"    -> Skipped by user")
            continue

        is_advance = ptype not in ("FlexibleSaving", "OnChain", "LiquidityMining")
        endpoint = "/v5/earn/advance/place-order" if is_advance else "/v5/earn/place-order"

        resp = client.post(endpoint, body)
        if resp and resp.get("retCode") == 0:
            print(f"    -> Subscribed successfully")
        else:
            print(f"    -> Failed: {resp}")


NO_EARLY_REDEEM_TYPES = ("DualAssets", "DoubleWin")


def execute_rebalance(client, allocations, total_capital, coin, drift_threshold, debug=False, dual_asset_max_days=1, logger=None):
    print("\n  Checking portfolio drift...")
    rebalance_needed = []

    for alloc in allocations:
        ptype = alloc["type"]
        target_weight = alloc["weight"]
        target_amount = total_capital * target_weight

        positions = get_positions_by_type(client, ptype)
        ptype_positions = [p for p in positions if p.get("coin", p.get("investCoin", "")) == coin or not p.get("coin")]
        actual_amount = sum(float(p.get("amount", p.get("investAmount", "0"))) for p in ptype_positions)
        actual_weight = actual_amount / total_capital if total_capital > 0 else 0

        drift = actual_weight - target_weight
        abs_drift = abs(drift)
        status = "DRIFT" if abs_drift > drift_threshold else "OK"

        print(f"    {ptype:<20} target={target_weight*100:.1f}% actual={actual_weight*100:.1f}% "
              f"drift={drift*100:+.1f}% [{status}]")

        if abs_drift > drift_threshold:
            rebalance_needed.append({
                "type": ptype,
                "risk": alloc["risk"],
                "weight": target_weight,
                "drift": drift,
                "target_amount": target_amount,
                "actual_amount": actual_amount,
                "diff": target_amount - actual_amount,
            })

    if not rebalance_needed:
        print("  No rebalancing needed.")
        return False

    print(f"\n  Rebalancing {len(rebalance_needed)} product(s)...")

    for item in rebalance_needed:
        ptype = item["type"]
        diff = item["diff"]

        if diff < 0:
            redeem_amount = abs(diff)

            if ptype in NO_EARLY_REDEEM_TYPES:
                print(f"    {ptype}: over-allocated by {redeem_amount:.0f} {coin} — "
                      f"no early redemption supported, will rebalance after settlement")
                continue

            valid, result = validate_order_amount(ptype, redeem_amount)
            if not valid:
                print(f"    {ptype}: redeem {redeem_amount:.0f} — {result}, skipping")
                continue

            if ptype == "LiquidityMining":
                print(f"    {ptype}: REDEEM {redeem_amount:.0f} → receiving {coin}")
                if logger:
                    logger.log(f"LiquidityMining redeem: amount={redeem_amount:.2f}, receiving coin={coin} "
                               f"(note: actual received amount may differ due to impermanent loss)")
            else:
                print(f"    {ptype}: REDEEM {redeem_amount:.0f} {coin}")

            positions = get_positions_by_type(client, ptype)
            if not positions:
                continue
            product_id = positions[0].get("productId", "")

            endpoint = "/v5/earn/place-order"
            body = {
                "category": ptype,
                "productId": str(product_id),
                "orderType": "Redeem",
                "amount": _format_amount(redeem_amount),
                "coin": coin,
                "accountType": "FUND",
                "orderLinkId": f"rp-rdm-{uuid.uuid4().hex[:12]}",
            }

            if debug:
                print(f"      [DEBUG] Redeem body:")
                print(f"      {json.dumps(body, indent=2)}")
                if logger:
                    logger.log(f"Rebalance redeem: {ptype} amount={redeem_amount:.2f}, coin={coin}, body={json.dumps(body)}")
            else:
                summary = {"Action": "Redeem (Rebalance)", "Type": ptype,
                           "Amount": f"{int(redeem_amount)} {coin}"}
                if client.confirm_operation(summary):
                    resp = client.post(endpoint, body)
                    if resp and resp.get("retCode") == 0:
                        print(f"      -> Redeemed successfully")
                    else:
                        print(f"      -> Failed: {resp}")

        elif diff > 0:
            if ptype in NO_EARLY_REDEEM_TYPES:
                fund_balance = get_fund_balance(client, coin)
                subscribe_amount = min(diff, fund_balance)
                if subscribe_amount < ORDER_LIMITS.get(ptype, {}).get("min", 0):
                    print(f"    {ptype}: need {diff:.0f} {coin} but available {fund_balance:.0f} "
                          f"< minimum {ORDER_LIMITS[ptype]['min']}, skipping")
                    continue
            else:
                subscribe_amount = diff

            valid, result = validate_order_amount(ptype, subscribe_amount)
            if not valid:
                print(f"    {ptype}: subscribe {subscribe_amount:.0f} — {result}, skipping")
                continue
            subscribe_amount = result if isinstance(result, float) else subscribe_amount

            print(f"    {ptype}: SUBSCRIBE {subscribe_amount:.0f} {coin}")

            sub_alloc = [{"type": ptype, "risk": item["risk"], "weight": 1.0}]
            execute_allocation(client, sub_alloc, subscribe_amount, coin, debug=debug,
                               dual_asset_max_days=dual_asset_max_days)

    return True


def check_drift(client, allocations, total_capital, drift_threshold):
    for alloc in allocations:
        ptype = alloc["type"]
        target_weight = alloc["weight"]
        positions = get_positions_by_type(client, ptype)
        actual_amount = sum(float(p.get("amount", p.get("investAmount", "0"))) for p in positions)
        actual_weight = actual_amount / total_capital if total_capital > 0 else 0
        if abs(actual_weight - target_weight) > drift_threshold:
            return True
    return False


def generate_report(allocations, total_capital, coin):
    print("\n" + "=" * 60)
    print("  RISK-PARITY ALLOCATION REPORT")
    print("=" * 60)
    print(f"  Total Capital: {total_capital} {coin}")
    print(f"  Investment Coin: {coin}")

    total_risk_score = sum(a["weight"] * a["risk"] for a in allocations)
    print(f"  Weighted Risk Score: {total_risk_score:.2f}/5")

    print(f"\n  {'Product Type':<20} {'Risk':<6} {'Weight':<10} {'Amount':<12} {'Risk Contrib'}")
    print(f"  {'-'*65}")
    for a in allocations:
        amount = total_capital * a["weight"]
        risk_contrib = a["weight"] * a["risk"] / total_risk_score * 100 if total_risk_score > 0 else 0
        print(f"  {a['type']:<20} {a['risk']:<6} {a['weight']*100:<9.1f}% {amount:<12.0f} {risk_contrib:.1f}%")
    print("=" * 60)


def run_strategy(args):
    debug = args.debug

    if debug and args.testnet:
        print("ERROR: --debug and --testnet are mutually exclusive.")
        sys.exit(1)

    logger = DebugLogger(enabled=debug, log_dir=getattr(args, "log_dir", None))

    env_override = "testnet" if args.testnet else None
    client = BybitClient(env_override=env_override)

    if not debug:
        client.verify_credentials()
    else:
        print("[DEBUG MODE] Skipping API key verification. No orders will be executed.")
        print(f"  Using base URL: {client.base_url}")

    coin = args.coin
    allowed_types = [t.strip() for t in args.allowed_types.split(",")]
    allowed_levels = [int(l.strip()) for l in args.allowed_levels.split(",")]

    print(f"\nStrategy: Risk-Parity Earn Allocator")
    print(f"  Coin: {coin}")
    print(f"  Allowed Types: {allowed_types}")
    print(f"  Allowed Risk Levels: {allowed_levels}")
    print(f"  Max Single: {args.max_alloc*100}%")
    print(f"  Min Single: {args.min_alloc*100}%")
    print(f"  Drift Threshold: {args.drift*100}%")
    print(f"  Dual Asset Pref: {args.dual_asset_pref}")
    print(f"  Dual Asset Max Duration: {args.dual_asset_max_days} day(s)")
    if debug:
        print(f"  Mode: DEBUG (dry-run)")
    if logger:
        logger.log(f"Parameters: coin={coin}, types={allowed_types}, levels={allowed_levels}, "
                   f"max_alloc={args.max_alloc}, min_alloc={args.min_alloc}, drift={args.drift}")

    print(f"\n  Checking coin support for '{coin}'...")
    support = check_coin_support(client, coin, allowed_types, debug, logger=logger)
    for ptype, supported in support.items():
        status = "supported" if supported else "NOT supported"
        print(f"    {ptype}: {status}")

    supported_types = [t for t in allowed_types if support.get(t, False)]
    unsupported = [t for t in allowed_types if not support.get(t, False)]
    if unsupported:
        print(f"  Removing unsupported types: {unsupported}")
    if not supported_types:
        print("  ERROR: No product types support this coin.")
        sys.exit(1)

    if "LiquidityMining" in supported_types and 3 in allowed_levels:
        print("\n  ⚠️  WARNING: Your configuration includes Liquidity Mining products.")
        print("     During rebalance, redeeming from liquidity pools may cause losses")
        print("     due to impermanent loss. Please ensure you understand this risk.")
        print("     The redeemed amount may be less than originally invested.")
        if logger:
            logger.log("WARNING: LiquidityMining included — impermanent loss risk during rebalance redemption")

    if debug:
        if not args.capital:
            print("  ERROR: --capital is required in debug mode.")
            sys.exit(1)
        total_capital = args.capital
        fund_balance = total_capital
        print(f"  Capital (debug): {total_capital} {coin}")
        if logger:
            logger.log(f"Debug capital: {total_capital} {coin}")
    else:
        total_capital, fund_balance, positions_detail = get_total_capital(client, coin, supported_types, logger=logger)
        if total_capital <= 0:
            print(f"  ERROR: No {coin} found in FUND account or earn positions.")
            sys.exit(1)

    print(f"\n  Fetching APR for each product type...")
    type_apr_map = {}
    for ptype in supported_types:
        apr = get_product_apr(client, ptype, coin, logger=logger)
        type_apr_map[ptype] = apr
        print(f"    {ptype}: APR={apr*100:.2f}%")

    allocations = calculate_weights(type_apr_map, allowed_levels, args.max_alloc, args.min_alloc, logger=logger)

    if not allocations:
        print("  ERROR: No eligible product types after weight calculation.")
        sys.exit(1)

    generate_report(allocations, total_capital, coin)

    if debug:
        execute_allocation(client, allocations, total_capital, coin, debug=True,
                           dual_asset_max_days=args.dual_asset_max_days, logger=logger)
        print(f"\n  [DEBUG] Allocation plan complete. Exiting.")
        logger.close()
        return

    mode = getattr(args, "mode", "initial")

    if mode == "drift-check":
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Drift check run...")
        if check_drift(client, allocations, total_capital, args.drift):
            print("  Portfolio has drifted. Rebalancing...")
            execute_rebalance(client, allocations, total_capital, coin, args.drift, debug=False,
                              dual_asset_max_days=args.dual_asset_max_days)
        else:
            print("  Portfolio within drift threshold. No rebalance needed.")
        generate_report(allocations, total_capital, coin)
        return

    # mode == "initial": execute initial allocation
    needed_amounts = {}
    for alloc in allocations:
        ptype = alloc["type"]
        target_amount = total_capital * alloc["weight"]
        positions = get_positions_by_type(client, ptype)
        ptype_positions = [p for p in positions if p.get("coin", p.get("investCoin", "")) == coin or not p.get("coin")]
        current_amount = sum(float(p.get("amount", p.get("investAmount", "0"))) for p in ptype_positions)
        diff = target_amount - current_amount
        if diff > 0:
            needed_amounts[ptype] = diff

    if needed_amounts:
        print(f"\n  New subscriptions needed (from FUND balance {fund_balance:.2f} {coin}):")
        for ptype, amt in needed_amounts.items():
            print(f"    {ptype}: +{amt:.2f} {coin}")

    sub_allocations = []
    for alloc in allocations:
        ptype = alloc["type"]
        if ptype in needed_amounts and needed_amounts[ptype] > 0:
            sub_amount = needed_amounts[ptype]
            valid, result = validate_order_amount(ptype, sub_amount)
            if valid:
                sub_allocations.append({**alloc, "_subscribe_amount": min(sub_amount, fund_balance)})

    if sub_allocations:
        execute_allocation_incremental(client, sub_allocations, coin, debug=False,
                                       dual_asset_max_days=args.dual_asset_max_days)

    print(f"\n  Initial allocation complete.")
    print(f"  To monitor drift daily, schedule a recurring task via CronCreate with:")
    print(f"    python scripts/risk_parity.py --coin {coin} --mode drift-check [same args as this run]")


def main():
    parser = argparse.ArgumentParser(description="Risk-Parity Earn Allocator")
    parser.add_argument("--capital", type=float, default=None,
                        help="Total capital (required for debug mode; auto-detected in live mode)")
    parser.add_argument("--coin", type=str, required=True,
                        help="Investment coin (e.g., USDT, BTC, ETH)")
    parser.add_argument("--allowed-types",
                        default="FlexibleSaving,OnChain,LiquidityMining,DualAssets,DoubleWin",
                        help="Allowed product types (comma-separated)")
    parser.add_argument("--allowed-levels", default="1,2,3,4,5",
                        help="Allowed risk levels (comma-separated)")
    parser.add_argument("--drift", type=float, default=0.1,
                        help="Drift threshold (0.1=10%%)")
    parser.add_argument("--max-alloc", type=float, default=0.75,
                        help="Max single allocation (0.75=75%%)")
    parser.add_argument("--min-alloc", type=float, default=0.00,
                        help="Min single allocation (0.00=0%%)")
    parser.add_argument("--dual-asset-pref", default="nearest-farthest",
                        help="Dual asset selection: nearest-farthest (default)")
    parser.add_argument("--dual-asset-max-days", type=float, default=1,
                        help="Dual asset max duration in days (default: 1)")
    parser.add_argument("--debug", action="store_true",
                        help="Debug mode: no API key needed, dry-run only")
    parser.add_argument("--testnet", action="store_true",
                        help="Use testnet API (requires API key, executes real orders on testnet)")
    parser.add_argument("--log-dir", type=str, default=None,
                        help="Directory for debug log file output (default: current directory)")
    parser.add_argument("--mode", type=str, default="initial", choices=["initial", "drift-check"],
                        help="Execution mode: 'initial' (first-time allocation) or 'drift-check' (scheduled rebalance check)")
    args = parser.parse_args()
    run_strategy(args)


if __name__ == "__main__":
    main()
