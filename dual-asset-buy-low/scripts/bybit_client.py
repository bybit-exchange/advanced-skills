"""
Bybit API Client with HMAC-SHA256 authentication.
All requests include mandatory headers: User-Agent: bybit-skill/1.3.0, X-Referer: bybit-skill
"""

import os
import sys
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

import requests

MAINNET_URL = "https://api.bybit.com"
TESTNET_URL = "https://api-testnet.bybit.com"
RECV_WINDOW = "5000"
SKILL_VERSION = "1.3.0"

MANDATORY_HEADERS = {
    "User-Agent": f"bybit-skill/{SKILL_VERSION}",
    "X-Referer": "bybit-skill",
}


class BybitClient:
    def __init__(self, env_override=None):
        self.api_key = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = os.environ.get("BYBIT_API_SECRET", "")
        if env_override:
            self.env = env_override.lower()
        else:
            self.env = os.environ.get("BYBIT_ENV", "mainnet").lower()
        self.base_url = TESTNET_URL if self.env == "testnet" else MAINNET_URL
        self._last_get_time = 0
        self._last_post_time = 0

    def verify_credentials(self):
        if not self.api_key or not self.api_secret:
            print("ERROR: BYBIT_API_KEY and BYBIT_API_SECRET environment variables are required.")
            print("\nPlease configure:")
            print('  export BYBIT_API_KEY="your_api_key"')
            print('  export BYBIT_API_SECRET="your_secret_key"')
            print('  export BYBIT_ENV="testnet"  # or "mainnet"')
            sys.exit(1)

        print(f"[{'TESTNET' if self.env == 'testnet' else 'MAINNET'}] Verifying API connection...")

        time_resp = self.get("/v5/market/time")
        if time_resp is None:
            print("ERROR: Failed to connect to Bybit API.")
            sys.exit(1)

        server_time = int(time_resp["result"]["timeSecond"])
        local_time = int(time.time())
        diff = abs(server_time - local_time)
        if diff > 5:
            print(f"WARNING: Clock drift detected ({diff}s). Please sync your system clock.")
            sys.exit(1)

        balance_resp = self.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        if balance_resp is None or balance_resp.get("retCode") != 0:
            ret_code = balance_resp.get("retCode") if balance_resp else "N/A"
            ret_msg = balance_resp.get("retMsg") if balance_resp else "Connection failed"
            print(f"ERROR: API verification failed. retCode={ret_code}, retMsg={ret_msg}")
            if ret_code == 10003:
                print("  -> Invalid API key.")
            elif ret_code == 10004:
                print("  -> Invalid signature. Check your API secret.")
            elif ret_code == 10005:
                print("  -> Insufficient permissions. Enable Read+Trade.")
            elif ret_code == 10010:
                print("  -> IP not whitelisted.")
            sys.exit(1)

        coins = balance_resp["result"].get("list", [{}])[0].get("coin", [])
        usdt_balance = "0"
        for coin in coins:
            if coin.get("coin") == "USDT":
                usdt_balance = coin.get("walletBalance", "0")
                break

        env_label = "TESTNET" if self.env == "testnet" else "MAINNET"
        print(f"  Connected to Bybit [{env_label}]")
        print(f"  API Key: {self.api_key[:5]}...{self.api_key[-4:]}")
        print(f"  Account: UNIFIED")
        print(f"  USDT Balance: {usdt_balance}")
        return True

    def _sign(self, timestamp, params_str):
        param_str = f"{timestamp}{self.api_key}{RECV_WINDOW}{params_str}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _rate_limit(self, method):
        now = time.time()
        if method == "GET":
            elapsed = now - self._last_get_time
            if elapsed < 0.1:
                time.sleep(0.1 - elapsed)
            self._last_get_time = time.time()
        else:
            elapsed = now - self._last_post_time
            if elapsed < 0.3:
                time.sleep(0.3 - elapsed)
            self._last_post_time = time.time()

    def get(self, endpoint, params=None):
        self._rate_limit("GET")
        timestamp = str(int(time.time() * 1000))
        query_string = urlencode(params) if params else ""
        sign = self._sign(timestamp, query_string)

        headers = {
            **MANDATORY_HEADERS,
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": sign,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        }

        url = f"{self.base_url}{endpoint}"
        if query_string:
            url += f"?{query_string}"

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200 and not resp.text.strip():
                print(f"HTTP {resp.status_code} (empty body) for GET {endpoint}")
                return {"retCode": resp.status_code, "retMsg": f"HTTP {resp.status_code}"}
            return resp.json()
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def post(self, endpoint, body=None):
        self._rate_limit("POST")
        timestamp = str(int(time.time() * 1000))
        json_body = json.dumps(body, separators=(",", ":")) if body else ""
        sign = self._sign(timestamp, json_body)

        headers = {
            **MANDATORY_HEADERS,
            "Content-Type": "application/json",
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": sign,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        }

        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.post(url, headers=headers, data=json_body, timeout=10)
            if resp.status_code != 200 and not resp.text.strip():
                print(f"HTTP {resp.status_code} (empty body) for POST {endpoint}")
                return {"retCode": resp.status_code, "retMsg": f"HTTP {resp.status_code}"}
            return resp.json()
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def confirm_operation(self, summary):
        print("\n" + "=" * 50)
        env_label = "TESTNET" if self.env == "testnet" else "MAINNET"
        print(f"[{env_label}] Operation Summary")
        print("-" * 50)
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print("-" * 50)

        if self.env == "testnet":
            print("(Testnet - executing without confirmation)")
            return True

        print('Please type "CONFIRM" to execute:')
        user_input = input("> ").strip()
        if user_input.upper() == "CONFIRM":
            return True
        print("Operation cancelled.")
        return False


if __name__ == "__main__":
    client = BybitClient()
    client.verify_credentials()
    print("\nBybit client initialized successfully.")
