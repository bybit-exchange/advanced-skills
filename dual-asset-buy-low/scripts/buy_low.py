"""
Dual Asset Buy-Low Recurring — DCA via Dual Asset products at strike price.
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

ORDER_SPLIT_INTERVAL = 5
FALLBACK_MAX_ORDER = 200000


class DebugLogger:
    def __init__(self, enabled=False, log_dir=None):
        self.enabled = enabled
        self.file = None
        if enabled:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            directory = log_dir or "."
            filepath = os.path.join(directory, f"buylow_debug_{ts}.log")
            self.file = open(filepath, "w", encoding="utf-8")
            self.log(f"=== Debug log started ===")
            print(f"  [DEBUG] Log file: {filepath}")

    def log(self, message):
        if not self.enabled:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}"
        if self.file:
            self.file.write(line + "\n")
            self.file.flush()

    def close(self):
        if self.file:
            self.log("=== Debug log ended ===")
            self.file.close()


def get_fund_balance(client, coin, logger=None):
    resp = client.get("/v5/asset/transfer/query-account-coins-balance", {
        "accountType": "FUND",
        "coin": coin,
    })
    if not resp or resp.get("retCode") != 0:
        print(f"  Failed to query FUND balance: {resp}")
        if logger:
            logger.log(f"FUND balance query failed: {resp}")
        return 0.0
    coins = resp["result"].get("balance", [])
    for c in coins:
        if c.get("coin") == coin:
            balance = float(c.get("transferBalance", "0"))
            if logger:
                logger.log(f"FUND balance for {coin}: {balance}")
            return balance
    if logger:
        logger.log(f"FUND balance: coin {coin} not found in response")
    return 0.0


def get_dual_asset_products(client, target_coin, quote_coin, logger=None):
    resp = client.get("/v5/earn/advance/product", {
        "category": "DualAssets",
        "coin": target_coin,
    })
    if not resp or resp.get("retCode") != 0:
        print(f"  Failed to fetch products: {resp}")
        if logger:
            logger.log(f"Product fetch failed: {resp}")
        return []
    products = resp["result"].get("list", [])
    filtered = [
        p for p in products
        if p.get("status") == "Available"
        and p.get("baseCoin") == target_coin
        and p.get("quoteCoin") == quote_coin
    ]
    if logger:
        logger.log(f"Fetched {len(products)} raw products, {len(filtered)} after filtering ({target_coin}/{quote_coin}, status=Available)")
    return filtered


def get_product_quotes(client, product_id, logger=None):
    resp = client.get("/v5/earn/advance/product-extra-info", {
        "category": "DualAssets",
        "productId": str(product_id),
    })
    if not resp or resp.get("retCode") != 0:
        if logger:
            logger.log(f"Quote query failed for productId={product_id}: {resp}")
        return None
    result = resp["result"]
    items = result.get("list", [])
    quote_data = items[0] if items else result
    if logger:
        buy_low_count = len(quote_data.get("buyLowPrice", []))
        logger.log(f"Quotes for productId={product_id}: {buy_low_count} buyLow strike(s) available")
    return quote_data


def find_best_quote(products, client, target_price, min_premium, preferred_duration, logger=None):
    candidates = []
    now_ms = int(time.time() * 1000)

    for product in products:
        product_id = product.get("productId")
        duration_raw = str(product.get("duration", "0"))
        duration = int(''.join(c for c in duration_raw if c.isdigit()) or "0")
        settlement_time = int(product.get("settlementTime", "0"))
        quotes = get_product_quotes(client, product_id, logger)
        if not quotes:
            continue

        buy_low_prices = quotes.get("buyLowPrice", [])
        current_price = float(quotes.get("currentPrice", "0"))

        for quote in buy_low_prices:
            expired_at = int(quote.get("expiredAt", "0"))
            if expired_at <= now_ms:
                if logger:
                    logger.log(f"  productId={product_id} strike={quote.get('selectPrice')} -> SKIPPED (expired)")
                continue

            strike = float(quote.get("selectPrice", "0"))
            apy_e8 = int(quote.get("apyE8", "0"))
            annual_yield = apy_e8 / 1e8

            if annual_yield < min_premium:
                if logger:
                    logger.log(f"  productId={product_id} strike={strike} apy={annual_yield*100:.2f}% -> REJECTED (premium {annual_yield*100:.2f}% < {min_premium*100:.2f}%)")
                continue

            if strike > target_price:
                if logger:
                    logger.log(f"  productId={product_id} strike={strike} apy={annual_yield*100:.2f}% -> REJECTED (strike {strike} > target {target_price})")
                continue

            if logger:
                logger.log(f"  productId={product_id} strike={strike} apy={annual_yield*100:.2f}% duration={duration}d -> ACCEPTED as candidate")
            candidates.append({
                "product": product,
                "productId": product_id,
                "strike": strike,
                "apyE8": apy_e8,
                "annual_yield": annual_yield,
                "duration": duration,
                "current_price": current_price,
                "settlement_time": settlement_time,
            })

    if not candidates:
        if logger:
            logger.log("No candidates met criteria")
        return None

    if preferred_duration == "shortest":
        candidates.sort(key=lambda x: (x["duration"], -(x["current_price"] - x["strike"])))
    elif preferred_duration == "longest":
        candidates.sort(key=lambda x: (-x["duration"], -(x["current_price"] - x["strike"])))
    else:
        candidates.sort(key=lambda x: -(x["current_price"] - x["strike"]))

    if logger:
        logger.log(f"Selected best from {len(candidates)} candidates: productId={candidates[0]['productId']} strike={candidates[0]['strike']} apy={candidates[0]['annual_yield']*100:.2f}%")
    return candidates[0]


def check_conditions(client, product_id, target_price, min_premium, logger=None):
    quotes = get_product_quotes(client, product_id, logger)
    if not quotes:
        return None

    now_ms = int(time.time() * 1000)
    buy_low_prices = quotes.get("buyLowPrice", [])

    for quote in buy_low_prices:
        expired_at = int(quote.get("expiredAt", "0"))
        if expired_at <= now_ms:
            continue
        strike = float(quote.get("selectPrice", "0"))
        apy_e8 = int(quote.get("apyE8", "0"))
        annual_yield = apy_e8 / 1e8

        if strike <= target_price and annual_yield >= min_premium:
            if logger:
                logger.log(f"Re-check PASSED: strike={strike} <= {target_price}, apy={annual_yield*100:.2f}% >= {min_premium*100:.2f}%")
            return {"strike": strike, "apyE8": apy_e8, "annual_yield": annual_yield}

    if logger:
        logger.log(f"Re-check FAILED: no quote meets strike<={target_price} and premium>={min_premium*100:.2f}%")
    return None


def _format_number(value):
    if float(value) == int(float(value)):
        return str(int(float(value)))
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def get_max_order_limit(client, product_id, select_price, logger=None):
    quotes = get_product_quotes(client, product_id, logger)
    if not quotes:
        return None
    buy_low_prices = quotes.get("buyLowPrice", [])
    target_str = _format_number(select_price)
    for quote in buy_low_prices:
        if _format_number(float(quote.get("selectPrice", "0"))) == target_str:
            max_amount = float(quote.get("maxInvestmentAmount", "0"))
            if logger:
                logger.log(f"maxInvestmentAmount for strike {select_price}: {max_amount}, chunk limit (80%): {max_amount * 0.8}")
            return max_amount
    if logger:
        logger.log(f"Strike {select_price} not found in quotes for productId={product_id}")
    return None


def build_order_body(best, amount, quote_coin, order_link_id):
    return {
        "category": "DualAssets",
        "productId": str(best["productId"]),
        "orderType": "Stake",
        "amount": _format_number(amount),
        "accountType": "FUND",
        "coin": quote_coin,
        "orderLinkId": order_link_id,
        "dualAssetsExtra": {
            "orderDirection": "BuyLow",
            "selectPrice": _format_number(best["strike"]),
            "apyE8": best["apyE8"],
        },
    }


def execute_with_split(client, best, invest_amount, quote_coin, target_price, min_premium, debug=False, logger=None):
    remaining = invest_amount
    total_placed = 0
    order_count = 0

    while remaining > 0:
        max_invest = get_max_order_limit(client, best["productId"], best["strike"], logger)
        if max_invest and max_invest > 0:
            chunk_limit = max_invest * 0.8
        else:
            chunk_limit = FALLBACK_MAX_ORDER
            if logger:
                logger.log(f"WARNING: Could not get maxInvestmentAmount, using fallback {FALLBACK_MAX_ORDER}")

        chunk = min(remaining, chunk_limit)
        order_link_id = f"buylow-{uuid.uuid4().hex[:16]}"

        print(f"  Refreshing quote before sub-order #{order_count + 1}...")
        fresh = check_conditions(client, best["productId"], target_price, min_premium, logger)
        if not fresh:
            if order_count == 0:
                print(f"  Quote expired or conditions no longer met. Cannot place order.")
            else:
                print(f"  Conditions no longer met. Stopping split orders.")
                print(f"  This round placed: {total_placed} {quote_coin} across {order_count} orders")
            break
        best = {**best, "strike": fresh["strike"], "apyE8": fresh["apyE8"], "annual_yield": fresh["annual_yield"]}

        body = build_order_body(best, chunk, quote_coin, order_link_id)

        if debug:
            print(f"\n  [DEBUG] Sub-order #{order_count + 1}:")
            print(f"    Max investment (API): {max_invest}")
            print(f"    Chunk limit (80%): {chunk_limit}")
            print(f"    Amount: {chunk} {quote_coin}")
            print(f"    Strike: {best['strike']}")
            print(f"    APY: {best['annual_yield'] * 100:.2f}%")
            print(f"    Request body:")
            print(f"    {json.dumps(body, indent=2)}")
            if logger:
                logger.log(f"Sub-order #{order_count + 1}: amount={chunk}, maxInvest={max_invest}, chunkLimit={chunk_limit}")
            remaining -= chunk
            total_placed += chunk
            order_count += 1
            if remaining > 0:
                print(f"    (Would wait {ORDER_SPLIT_INTERVAL}s before next sub-order)")
            continue

        summary = {
            "Action": "Subscribe Dual Asset (BuyLow)",
            "Target Coin": best["product"].get("baseCoin", ""),
            "Amount": f"{chunk} {quote_coin}",
            "Strike Price": f"{best['strike']}",
            "Premium APY": f"{best['annual_yield'] * 100:.2f}%",
            "Duration": f"{best['duration']} days",
            "Current Price": f"{best['current_price']}",
            "Sub-order": f"#{order_count + 1}" if invest_amount > chunk_limit else "N/A",
        }

        if not client.confirm_operation(summary):
            print("  Order cancelled by user.")
            break

        resp = client.post("/v5/earn/advance/place-order", body)
        if resp and resp.get("retCode") == 0:
            print(f"  Sub-order #{order_count + 1} success! Order: {resp['result'].get('orderId', 'N/A')}")
            remaining -= chunk
            total_placed += chunk
            order_count += 1
        else:
            print(f"  Sub-order #{order_count + 1} failed: {resp}")
            break

        if remaining > 0:
            print(f"  Waiting {ORDER_SPLIT_INTERVAL}s before next sub-order...")
            time.sleep(ORDER_SPLIT_INTERVAL)

    return total_placed, order_count


def run_strategy(args):
    debug = args.debug

    if debug and args.testnet:
        print("ERROR: --debug and --testnet are mutually exclusive.")
        sys.exit(1)

    logger = DebugLogger(enabled=debug, log_dir=args.log_dir)

    env_override = "testnet" if args.testnet else None
    client = BybitClient(env_override=env_override)

    if not debug:
        client.verify_credentials()
    else:
        print("[DEBUG MODE] Skipping API key verification. No orders will be executed.")
        print(f"  Using base URL: {client.base_url}")

    schedule_seconds = 86400 if args.schedule == "daily" else 604800

    print(f"\nStrategy: Dual Asset Buy-Low Recurring")
    print(f"  Target Coin: {args.target_coin}")
    print(f"  Quote Coin: {args.quote_coin}")
    print(f"  Target Price: {args.target_price} {args.quote_coin}")
    print(f"  Invest/Round: {args.invest} {args.quote_coin}")
    print(f"  Min Premium: {args.min_premium * 100}%")
    print(f"  Schedule: {args.schedule}")
    print(f"  Duration Pref: {args.duration_pref}")
    if debug:
        print(f"  Mode: DEBUG (dry-run, no actual orders)")

    logger.log(f"Strategy params: targetCoin={args.target_coin} quoteCoin={args.quote_coin} targetPrice={args.target_price} invest={args.invest} minPremium={args.min_premium} schedule={args.schedule} durationPref={args.duration_pref}")

    products = get_dual_asset_products(client, args.target_coin, args.quote_coin, logger)
    if not products:
        print(f"\n  ERROR: No Dual Asset products available for '{args.target_coin}/{args.quote_coin}'.")
        all_resp = client.get("/v5/earn/advance/product", {"category": "DualAssets"})
        all_products = all_resp.get("result", {}).get("list", []) if all_resp else []
        available_pairs = sorted(set(
            f"{p.get('baseCoin')}/{p.get('quoteCoin')}"
            for p in all_products if p.get("baseCoin") and p.get("quoteCoin")
        ))
        if available_pairs:
            print(f"  Supported pairs: {', '.join(available_pairs)}")
        else:
            print("  No Dual Asset products are currently available on the platform.")
        logger.log(f"No products found. Available pairs: {available_pairs}")
        logger.close()
        if debug:
            return
        else:
            sys.exit(1)
    print(f"  Product check passed: {len(products)} Dual Asset product(s) available for {args.target_coin}/{args.quote_coin}")

    last_expiry_time = 0

    while True:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Running buy-low scan...")
        logger.log("--- New scan round ---")

        now_ms = int(time.time() * 1000)
        if last_expiry_time > 0 and now_ms < last_expiry_time:
            remaining_hours = (last_expiry_time - now_ms) / 3600000
            print(f"  Previous order not yet settled ({remaining_hours:.1f}h remaining). Skipping.")
            logger.log(f"Skipping: previous order not settled ({remaining_hours:.1f}h remaining)")
            time.sleep(schedule_seconds)
            continue

        products = get_dual_asset_products(client, args.target_coin, args.quote_coin, logger)
        print(f"  Available {args.target_coin}/{args.quote_coin} dual asset products: {len(products)}")

        if not products:
            print(f"  ERROR: No dual asset products available for {args.target_coin}/{args.quote_coin}.")
            print(f"  Please verify that the target coin '{args.target_coin}' has BuyLow products quoted in '{args.quote_coin}'.")
            logger.close()
            if debug:
                return
            else:
                sys.exit(1)

        if not debug:
            balance = get_fund_balance(client, args.quote_coin, logger)
            print(f"  FUND account {args.quote_coin} balance: {balance}")
            if balance < args.invest:
                print(f"  Insufficient balance ({balance} < {args.invest}). Skipping this round.")
                logger.log(f"Insufficient balance: {balance} < {args.invest}")
                time.sleep(schedule_seconds)
                continue

        best = find_best_quote(
            products, client, args.target_price, args.min_premium, args.duration_pref, logger
        )

        if not best:
            print(f"  No quotes meet criteria (strike ≤ {args.target_price}, premium ≥ {args.min_premium*100}%)")
            if debug:
                logger.close()
                return
            time.sleep(schedule_seconds)
            continue

        print(f"  Best match: strike={best['strike']}, "
              f"APY={best['annual_yield']*100:.2f}%, duration={best['duration']}d")

        if debug:
            print(f"\n  [DEBUG] Selected product details:")
            print(f"    Product ID: {best['productId']}")
            print(f"    Base Coin: {best['product'].get('baseCoin', '')}")
            print(f"    Quote Coin: {best['product'].get('quoteCoin', '')}")
            print(f"    Strike Price: {best['strike']}")
            print(f"    Current Price: {best['current_price']}")
            print(f"    APY: {best['annual_yield'] * 100:.2f}%")
            print(f"    Duration: {best['duration']} days")
            print(f"    Settlement Time: {best['settlement_time']}")

        total_placed, order_count = execute_with_split(
            client, best, args.invest, args.quote_coin,
            args.target_price, args.min_premium, debug=debug, logger=logger
        )

        if total_placed > 0 and not debug:
            last_expiry_time = best["settlement_time"]
            print(f"  Recorded settlement time: {last_expiry_time} "
                  f"(~{(last_expiry_time - now_ms) / 3600000:.1f}h from now)")

        if debug:
            print(f"\n  [DEBUG] Summary: Would place {total_placed} {args.quote_coin} "
                  f"across {order_count} sub-orders")
            logger.log(f"Summary: {total_placed} {args.quote_coin} across {order_count} sub-orders")
            logger.close()
            return

        print(f"  Round complete. Placed {total_placed} {args.quote_coin} in {order_count} orders.")
        print(f"  Next scan in {args.schedule}...")
        time.sleep(schedule_seconds)


def main():
    parser = argparse.ArgumentParser(description="Dual Asset Buy-Low Recurring Strategy")
    parser.add_argument("--target-coin", default="BTC", help="Target coin to accumulate")
    parser.add_argument("--quote-coin", default="USDT", help="Quote coin for investment (default: USDT)")
    parser.add_argument("--target-price", type=float, required=True, help="Max acceptable strike price")
    parser.add_argument("--invest", type=float, default=500, help="Investment per round in quote coin")
    parser.add_argument("--min-premium", type=float, default=0.10, help="Min annualized premium (0.10=10%%)")
    parser.add_argument("--schedule", choices=["daily", "weekly"], default="daily", help="Execution frequency")
    parser.add_argument("--duration-pref", choices=["shortest", "longest", "balanced"], default="shortest")
    parser.add_argument("--debug", action="store_true", help="Debug mode: no API key needed, dry-run only")
    parser.add_argument("--log-dir", default=None, help="Directory for debug log file (default: current directory)")
    parser.add_argument("--testnet", action="store_true", help="Use testnet API (requires API key, executes real orders on testnet)")
    args = parser.parse_args()
    run_strategy(args)


if __name__ == "__main__":
    main()
