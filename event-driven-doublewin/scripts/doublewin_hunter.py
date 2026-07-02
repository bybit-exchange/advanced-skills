"""
Event-Driven DoubleWin Hunter — Profit from volatility around major events.
All API requests include: User-Agent: bybit-skill/1.3.0, X-Referer: bybit-skill
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from bybit_client import BybitClient

MAX_CAPITAL_PER_TRADE = 1000
DEDUP_FILE = "doublewin_trade_history.json"
CHECK_INTERVAL_SECONDS = 28800

class DebugLogger:
    def __init__(self, enabled=False, log_dir=None):
        self.enabled = enabled
        self.file = None
        if enabled:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            directory = log_dir or "."
            filepath = os.path.join(directory, f"doublewin_debug_{ts}.log")
            self.file = open(filepath, "w", encoding="utf-8")
            self.log("=== Debug log started ===")
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


RSS_SOURCES = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "theblock": "https://www.theblock.co/rss.xml",
}
INVESTING_CALENDAR_URL = "https://www.investing.com/economic-calendar/"

RSS_HEADERS = {
    "User-Agent": "bybit-skill/1.3.0",
    "X-Referer": "bybit-skill",
}


def parse_rss_date(date_str):
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str.strip())
        return int(dt.timestamp() * 1000)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def make_event_id(title, source, time_ms):
    raw = f"{title}|{source}|{time_ms}"
    return hashlib.md5(raw.encode()).hexdigest()


def fetch_rss_feed(url, source_name, logger=None):
    events = []
    try:
        resp = requests.get(url, headers=RSS_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  [{source_name}] HTTP {resp.status_code}")
            if logger:
                logger.log(f"RSS fetch failed [{source_name}]: HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.text)

        ns = {}
        for elem in root.iter():
            if "}" in elem.tag:
                uri = elem.tag.split("}")[0] + "}"
                prefix = elem.tag.split("}")[1]
                if uri not in ns.values():
                    ns[f"ns{len(ns)}"] = uri

        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items:
            title_el = item.find("title")
            if title_el is None:
                title_el = item.find("{http://www.w3.org/2005/Atom}title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            desc_el = item.find("description")
            if desc_el is None:
                desc_el = item.find("{http://www.w3.org/2005/Atom}summary")
            summary = ""
            if desc_el is not None and desc_el.text:
                summary = desc_el.text.strip()[:300]

            pub_el = item.find("pubDate")
            if pub_el is None:
                pub_el = item.find("{http://www.w3.org/2005/Atom}published")
            if pub_el is None:
                pub_el = item.find("{http://purl.org/dc/elements/1.1/}date")
            date_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

            event_time_ms = parse_rss_date(date_str)
            if not event_time_ms:
                continue
            if not title:
                continue

            events.append({
                "id": make_event_id(title, source_name, event_time_ms),
                "title": title,
                "summary": summary,
                "source": source_name,
                "event_time_ms": event_time_ms,
                "raw_time_str": date_str,
            })
    except Exception as e:
        print(f"  [{source_name}] Error fetching RSS: {e}")
        if logger:
            logger.log(f"RSS exception [{source_name}]: {e}")
    if logger:
        logger.log(f"RSS [{source_name}]: fetched {len(events)} events")
    return events


def fetch_coindesk_rss(logger=None):
    return fetch_rss_feed(RSS_SOURCES["coindesk"], "coindesk", logger)


def fetch_cointelegraph_rss(logger=None):
    return fetch_rss_feed(RSS_SOURCES["cointelegraph"], "cointelegraph", logger)


def fetch_theblock_rss(logger=None):
    return fetch_rss_feed(RSS_SOURCES["theblock"], "theblock", logger)


def fetch_investing_calendar(logger=None):
    events = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "X-Referer": "bybit-skill",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(INVESTING_CALENDAR_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  [investing] HTTP {resp.status_code}")
            return []

        import re
        rows = re.findall(r'<tr[^>]*class="js-event-item"[^>]*>(.*?)</tr>', resp.text, re.DOTALL)
        for row in rows[:50]:
            time_match = re.search(r'data-event-datetime="([^"]+)"', row)
            title_match = re.search(r'class="[^"]*event[^"]*"[^>]*>(.*?)</(?:a|td|span)', row, re.DOTALL)
            impact_match = re.search(r'sentiment[^"]*bull(\d)', row)

            if not time_match or not title_match:
                continue

            impact_level = int(impact_match.group(1)) if impact_match else 1
            if impact_level < 2:
                continue

            date_str = time_match.group(1)
            title_raw = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            if not title_raw:
                continue

            event_time_ms = parse_rss_date(date_str)
            if not event_time_ms:
                for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                        event_time_ms = int(dt.timestamp() * 1000)
                        break
                    except ValueError:
                        continue

            if not event_time_ms:
                continue

            events.append({
                "id": make_event_id(title_raw, "investing", event_time_ms),
                "title": title_raw,
                "summary": f"Economic calendar event (impact: {'high' if impact_level >= 3 else 'medium'})",
                "source": "investing",
                "event_time_ms": event_time_ms,
                "raw_time_str": date_str,
            })
    except Exception as e:
        print(f"  [investing] Error fetching calendar: {e}")
        if logger:
            logger.log(f"Investing calendar exception: {e}")
    if logger:
        logger.log(f"Investing calendar: fetched {len(events)} events")
    return events


def scan_all_sources(logger=None):
    print("  Fetching from data sources...")
    all_events = []

    sources = [
        ("CoinDesk", fetch_coindesk_rss),
        ("CoinTelegraph", fetch_cointelegraph_rss),
        ("The Block", fetch_theblock_rss),
        ("Investing.com", fetch_investing_calendar),
    ]

    for name, fetch_fn in sources:
        events = fetch_fn(logger)
        print(f"    {name}: {len(events)} events")
        all_events.extend(events)

    all_events.sort(key=lambda e: e["event_time_ms"])
    return all_events


def get_dedup_file_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), DEDUP_FILE)


def load_dedup_history():
    path = get_dedup_file_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if data and isinstance(data[0], str):
            return [{"id": item, "title": "", "source": "", "time_ms": 0, "summary": ""} for item in data]
        return data
    except (json.JSONDecodeError, IOError):
        return []


def save_dedup_history(history):
    path = get_dedup_file_path()
    trimmed = history[-200:]
    with open(path, "w") as f:
        json.dump(trimmed, f, indent=2)


def request_agent_dedup(event, history, debug=False, auto_mode=False, logger=None):
    recent = [h for h in history if isinstance(h, dict) and h.get("title")][-30:]
    if not recent:
        if logger:
            logger.log(f"Dedup: no titled history to compare, treating as new event")
        return False

    print("\n  " + "=" * 56)
    print("  EVENT DEDUP CHECK (AI Agent Judgment)")
    print("  " + "-" * 56)
    print(f"  Candidate event:")
    print(f"    Title: {event['title']}")
    print(f"    Source: {event['source']}")
    print(f"    Summary: {event.get('summary', 'N/A')[:150]}")
    print("  " + "-" * 56)
    display = recent[-10:]
    print(f"  Previously traded events (showing {len(display)} of {len(recent)}):")
    for i, h in enumerate(display, 1):
        print(f"    {i}. [{h.get('source', '')}] {h.get('title', '')}")
    print("  " + "-" * 56)

    if debug or auto_mode:
        print(f"  [{'DEBUG' if debug else 'AUTO'}] Auto-judging as 'not duplicate'")
        if logger:
            logger.log(f"Dedup auto-judge: not duplicate (mode={'debug' if debug else 'auto'})")
        return False

    print("  Is this candidate the SAME event as any listed above?")
    print("  (Different headlines about the same underlying event count as same)")
    while True:
        answer = input("  Same event? [yes/no]: ").strip().lower()
        if answer in ("yes", "y"):
            if logger:
                logger.log(f"Dedup agent judgment: DUPLICATE — '{event['title'][:60]}'")
            return True
        if answer in ("no", "n"):
            if logger:
                logger.log(f"Dedup agent judgment: NEW — '{event['title'][:60]}'")
            return False
        print("  Please enter yes or no.")


def is_duplicate(event, history, debug=False, auto_mode=False, logger=None):
    known_ids = [h["id"] for h in history if isinstance(h, dict)]
    if event["id"] in known_ids:
        if logger:
            logger.log(f"Dedup exact match (ID): '{event['title'][:60]}'")
        return True
    return request_agent_dedup(event, history, debug=debug, auto_mode=auto_mode, logger=logger)


def request_agent_rating(event, target_coin, debug=False, auto_rate=False):
    print("\n" + "=" * 60)
    print("  EVENT RATING REQUEST")
    print("  " + "-" * 56)
    print(f"  Source: {event['source']}")
    print(f"  Title: {event['title']}")
    print(f"  Summary: {event.get('summary', 'N/A')[:200]}")
    print(f"  Event Time: {event['raw_time_str']}")
    print(f"  Target Coin: {target_coin}")
    print("  " + "-" * 56)

    if debug or auto_rate:
        print(f"  [{'DEBUG' if debug else 'AUTO'}] Auto-rating as 'medium' (non-interactive mode)")
        return "medium"

    print("  Rate this event's expected impact on target coin price:")
    print("    high   — Major volatility expected")
    print("    medium — Moderate volatility possible")
    print("    low    — Minor impact, not worth trading")
    print("    skip   — Ignore this event entirely")
    print("  " + "-" * 56)

    while True:
        rating = input("  Rating [high/medium/low/skip]: ").strip().lower()
        if rating in ("high", "medium", "low", "skip"):
            return rating
        print("  Invalid input. Please enter: high, medium, low, or skip")


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


def get_doublewin_products(client, target_coin, logger=None):
    resp = client.get("/v5/earn/advance/product", {
        "category": "DoubleWin",
        "coin": target_coin,
    })
    if not resp or resp.get("retCode") != 0:
        print(f"  Failed to fetch DoubleWin products: {resp}")
        if logger:
            logger.log(f"DoubleWin product fetch failed: {resp}")
        return []
    now_ms = int(time.time() * 1000)
    products = resp["result"].get("list", [])
    filtered = [
        p for p in products
        if int(p.get("subscribeEndAt", "0")) > now_ms
        and not p.get("isRfqProduct", False)
    ]
    if logger:
        logger.log(f"DoubleWin products: {len(products)} total, {len(filtered)} subscribable for {target_coin}")
    return filtered


def get_product_details(client, product_id):
    resp = client.get("/v5/earn/advance/product-extra-info", {
        "category": "DoubleWin",
        "productId": str(product_id),
    })
    if not resp or resp.get("retCode") != 0:
        return None
    result = resp["result"]
    items = result.get("list", [])
    if items:
        return items[0]
    return result


def select_product_with_leverage(client, products, event_time_ms, event_level, preferred_leverage, logger=None):
    valid = []
    for p in products:
        settlement_ms = int(p.get("settlementTime", "0"))
        if settlement_ms <= event_time_ms:
            continue
        details = get_product_details(client, p.get("productId"))
        if not details:
            continue
        leverage_raw = details.get("leverage")
        if not leverage_raw:
            continue
        if isinstance(leverage_raw, str):
            leverage_val = float(leverage_raw)
        elif isinstance(leverage_raw, list):
            leverage_val = float(leverage_raw[0].get("multiplier", "0"))
        else:
            leverage_val = float(leverage_raw)
        current_price = details.get("currentPrice", "0")
        valid.append({
            "product": p,
            "details": details,
            "leverage_val": leverage_val,
            "settlement_ms": settlement_ms,
            "current_price": current_price,
        })

    if not valid:
        if logger:
            logger.log(f"No valid product found (settlement > event_time={event_time_ms})")
        return None, None, None

    if preferred_leverage == "low":
        valid.sort(key=lambda x: x["leverage_val"])
    elif preferred_leverage == "high":
        valid.sort(key=lambda x: -x["leverage_val"])
    elif preferred_leverage == "auto":
        if event_level == "high":
            valid.sort(key=lambda x: -x["leverage_val"])
        else:
            valid.sort(key=lambda x: x["leverage_val"])

    chosen = valid[0]
    leverage_info = {"multiplier": str(chosen["leverage_val"])}
    if logger:
        logger.log(f"Selected product: id={chosen['product'].get('productId')}, leverage={chosen['leverage_val']}x, settlement={chosen['settlement_ms']}")
    return chosen["product"], leverage_info, chosen["current_price"]


def execute_doublewin(client, product, leverage_info, amount, event_desc, initial_price="0", debug=False):
    leverage_val = leverage_info.get("multiplier", leverage_info.get("leverage", "2"))

    body = {
        "category": "DoubleWin",
        "productId": str(product.get("productId")),
        "orderType": "Stake",
        "amount": str(int(amount)),
        "accountType": "FUND",
        "coin": "USDT",
        "orderLinkId": f"dw-{uuid.uuid4().hex[:16]}",
        "doubleWinStakeExtra": {
            "leverage": str(leverage_val),
            "initialPrice": str(initial_price),
        },
    }

    if debug:
        print(f"\n  [DEBUG] Planned DoubleWin order:")
        print(f"    Underlying: {product.get('underlyingAsset', 'N/A')}")
        print(f"    Amount: {amount} USDT")
        print(f"    Leverage: {leverage_val}x")
        print(f"    Event: {event_desc}")
        print(f"    Settlement: {product.get('settlementTime', 'N/A')}")
        print(f"    Request body:")
        print(f"    {json.dumps(body, indent=2)}")
        return True

    summary = {
        "Action": "Subscribe DoubleWin",
        "Underlying": product.get("underlyingAsset", "BTC"),
        "Amount": f"{amount} USDT",
        "Leverage": f"{leverage_val}x",
        "Event Trigger": event_desc,
        "Duration": f"{product.get('duration', 'N/A')} hours",
    }

    if not client.confirm_operation(summary):
        print("  Order cancelled by user.")
        return False

    resp = client.post("/v5/earn/advance/place-order", body)
    if resp and resp.get("retCode") == 0:
        print(f"  DoubleWin subscribed! Order: {resp['result'].get('orderId', 'N/A')}")
        return True
    else:
        print(f"  Subscription failed: {resp}")
        return False


def check_settlements(client):
    resp = client.get("/v5/earn/advance/order", {
        "category": "DoubleWin",
        "limit": "10",
    })
    if not resp or resp.get("retCode") != 0:
        return
    orders = resp["result"].get("list", [])
    settled = [o for o in orders if o.get("status") == "Settled"]
    if settled:
        wins = sum(1 for o in settled if o.get("settlementResult") == "Win")
        total = len(settled)
        print(f"  Recent settlements: {wins}/{total} wins ({wins/total*100:.0f}% win rate)")


def run_strategy(args):
    debug = args.debug

    if debug and args.testnet:
        print("ERROR: --debug and --testnet are mutually exclusive.")
        sys.exit(1)

    logger = DebugLogger(enabled=debug, log_dir=args.log_dir)

    env_override = "testnet" if args.testnet else None
    client = BybitClient(env_override=env_override)

    if args.capital_per_trade > MAX_CAPITAL_PER_TRADE:
        print(f"ERROR: capitalPerTrade cannot exceed {MAX_CAPITAL_PER_TRADE} USDT.")
        sys.exit(1)

    if not debug:
        client.verify_credentials()
    else:
        print("[DEBUG MODE] Skipping API key verification. No orders will be executed.")
        print(f"  Using base URL: {client.base_url}")

    print(f"\nStrategy: Event-Driven DoubleWin Hunter")
    print(f"  Target: {args.target_coin}")
    print(f"  Capital/Trade: {args.capital_per_trade} USDT (max {MAX_CAPITAL_PER_TRADE})")
    print(f"  Entry Window: {args.entry_window}h before event")
    print(f"  Min Level: {args.min_level}")
    print(f"  Leverage: {args.leverage}")
    print(f"  Account: FUND")
    if debug:
        print(f"  Mode: DEBUG (dry-run, no actual orders)")

    logger.log(f"Strategy params: target={args.target_coin} capital={args.capital_per_trade} entryWindow={args.entry_window}h minLevel={args.min_level} leverage={args.leverage}")

    products = get_doublewin_products(client, args.target_coin, logger)
    if not products:
        print(f"\n  ERROR: No DoubleWin products available for '{args.target_coin}'.")
        all_resp = client.get("/v5/earn/advance/product", {"category": "DoubleWin"})
        all_products = all_resp.get("result", {}).get("list", []) if all_resp else []
        available_coins = sorted(set(p.get("underlyingAsset", "") for p in all_products if p.get("underlyingAsset")))
        if available_coins:
            print(f"  Supported coins: {', '.join(available_coins)}")
        else:
            print("  No DoubleWin products are currently available on the platform.")
        logger.log(f"No products found. Available coins: {available_coins}")
        logger.close()
        if debug:
            return
        else:
            sys.exit(1)
    print(f"  Product check passed: {len(products)} DoubleWin product(s) available for {args.target_coin}")

    last_settlement_time = 0
    dedup_history = load_dedup_history()
    print(f"  Dedup history: {len(dedup_history)} past events loaded")
    logger.log(f"Loaded dedup history: {len(dedup_history)} entries")

    while True:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Scanning events...")
        logger.log("--- New scan round ---")

        now_ms = int(time.time() * 1000)
        if last_settlement_time > 0 and now_ms < last_settlement_time:
            remaining_hours = (last_settlement_time - now_ms) / 3600000
            print(f"  Previous order not yet settled ({remaining_hours:.1f}h remaining). Skipping.")
            logger.log(f"Skipping: previous order not settled ({remaining_hours:.1f}h remaining)")
            if debug:
                logger.close()
                return
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue

        events = scan_all_sources(logger)
        print(f"  Total events fetched: {len(events)}")
        logger.log(f"Total events fetched from all sources: {len(events)}")

        entry_window_ms = args.entry_window * 3600 * 1000
        recency_window_ms = args.entry_window * 3600 * 1000
        actionable_events = []
        for event in events:
            time_diff = event["event_time_ms"] - now_ms
            if 0 < time_diff <= entry_window_ms:
                event["window_type"] = "upcoming"
                actionable_events.append(event)
                logger.log(f"  UPCOMING ({time_diff/3600000:.1f}h): {event['title'][:80]}")
            elif -recency_window_ms <= time_diff <= 0:
                event["window_type"] = "recent"
                actionable_events.append(event)
                logger.log(f"  RECENT ({-time_diff/3600000:.1f}h ago): {event['title'][:80]}")

        upcoming_count = sum(1 for e in actionable_events if e["window_type"] == "upcoming")
        recent_count = sum(1 for e in actionable_events if e["window_type"] == "recent")
        print(f"  Actionable events: {len(actionable_events)} "
              f"(upcoming: {upcoming_count}, recent news: {recent_count})")

        if not actionable_events:
            print("  No events in entry window.")
            if not debug:
                check_settlements(client)
            if debug:
                print("\n  [DEBUG] No actionable events found. Exiting.")
                logger.close()
                return
            print(f"  Next scan in 8h...")
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue

        traded_this_round = False
        for event in actionable_events:
            if is_duplicate(event, dedup_history, debug=debug, auto_mode=args.testnet, logger=logger):
                print(f"  [SKIP] Already traded on: {event['title'][:60]}")
                continue

            rating = request_agent_rating(event, args.target_coin, debug=debug, auto_rate=args.testnet)
            logger.log(f"Event rated '{rating}': {event['title'][:80]}")

            if rating in ("low", "skip"):
                print(f"  [SKIP] Rated '{rating}': {event['title'][:60]}")
                continue
            if args.min_level == "high" and rating != "high":
                print(f"  [SKIP] Requires 'high', got '{rating}': {event['title'][:60]}")
                continue

            print(f"\n  Event qualified [{rating.upper()}]: {event['title'][:80]}")
            logger.log(f"Event qualified [{rating}]: {event['title'][:80]}")

            if not debug:
                balance = get_fund_balance(client, "USDT", logger)
                print(f"  FUND balance: {balance} USDT")
                if balance < args.capital_per_trade:
                    print(f"  Insufficient balance ({balance} < {args.capital_per_trade}). Skipping.")
                    logger.log(f"Insufficient balance: {balance} < {args.capital_per_trade}")
                    break

            products = get_doublewin_products(client, args.target_coin, logger)
            if not products:
                print("  No DoubleWin products available.")
                continue

            product, leverage_info, initial_price = select_product_with_leverage(
                client, products, event["event_time_ms"], rating, args.leverage, logger
            )
            if not product or not leverage_info:
                print(f"  No suitable product found (settlement > event time with valid leverage).")
                continue

            print(f"  Selected product: ID={product.get('productId')}, "
                  f"settlement={product.get('settlementTime')}, "
                  f"leverage={leverage_info['multiplier']}x")

            success = execute_doublewin(
                client, product, leverage_info,
                args.capital_per_trade, event["title"],
                initial_price=initial_price, debug=debug
            )

            if success:
                last_settlement_time = int(product.get("settlementTime", "0"))
                dedup_history.append({
                    "id": event["id"],
                    "title": event["title"],
                    "source": event["source"],
                    "time_ms": event["event_time_ms"],
                    "summary": event.get("summary", ""),
                })
                save_dedup_history(dedup_history)
                print(f"  Recorded settlement time: {last_settlement_time}")
                logger.log(f"Trade success: settlement={last_settlement_time}, event='{event['title'][:60]}'")
                traded_this_round = True
                break

        if debug:
            if not traded_this_round:
                print("\n  [DEBUG] No trade executed this round.")
            print("\n  [DEBUG] Summary complete. Exiting.")
            logger.close()
            return

        if not traded_this_round:
            check_settlements(client)

        print(f"  Next scan in 8h...")
        time.sleep(CHECK_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Event-Driven DoubleWin Hunter")
    parser.add_argument("--target-coin", default="BTC", help="Underlying asset")
    parser.add_argument("--capital-per-trade", type=float, default=200,
                        help=f"USDT per trade (max {MAX_CAPITAL_PER_TRADE})")
    parser.add_argument("--entry-window", type=float, default=24,
                        help="Hours before event to enter")
    parser.add_argument("--min-level", choices=["medium", "high"], default="medium",
                        help="Minimum event level")
    parser.add_argument("--leverage", choices=["auto", "low", "high"], default="auto",
                        help="Leverage selection strategy")
    parser.add_argument("--debug", action="store_true",
                        help="Debug mode: no API key needed, dry-run only")
    parser.add_argument("--log-dir", default=None,
                        help="Directory for debug log file (default: current directory)")
    parser.add_argument("--testnet", action="store_true",
                        help="Use testnet API (requires API key, executes real orders on testnet)")
    args = parser.parse_args()
    run_strategy(args)


if __name__ == "__main__":
    main()
