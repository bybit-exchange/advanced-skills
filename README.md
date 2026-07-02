# advanced-skills

A collection of advanced, official Bybit trading and yield-management skills for
use with Claude Code, the Claude Agent SDK, and any AI assistant that supports
the [Anthropic skill format](https://docs.claude.com/en/docs/agents-and-tools/agent-skills).

Each skill is a self-contained directory that ships a `SKILL.md` (the entry
point loaded by the assistant), Python scripts that call the Bybit v5 API, and
API reference material the agent can consult while reasoning.

## Repository layout

```
advanced-skills/
├── dual-asset-buy-low/           # Recurring DCA via Dual Asset products
│   ├── SKILL.md                  # Skill entry point (frontmatter + prose)
│   ├── scripts/
│   │   ├── buy_low.py            # Main strategy script
│   │   └── bybit_client.py       # Shared signed-request client
│   └── reference/
│       └── dual-asset-api.md     # Endpoint reference
├── risk-parity-allocator/        # APR / risk-parity Earn allocator
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── risk_parity.py
│   │   └── bybit_client.py
│   └── reference/
│       └── earn-api.md
└── event-driven-doublewin/       # News/calendar-driven DoubleWin subscriber
    ├── SKILL.md
    ├── scripts/
    │   ├── doublewin_hunter.py
    │   └── bybit_client.py
    └── reference/
        └── doublewin-api.md
```

## Skills

### 1. `dual-asset-buy-low`

**Recurring DCA via Bybit Dual Asset products.**

Dual Asset lets you subscribe to a structured product that either buys your
target coin at a strike price below spot (if the market dips to that strike at
settlement), or returns your quote currency plus yield (if it doesn't). This
skill turns that into a systematic buy-the-dip DCA engine:

- Reads a target coin, strike-discount range, subscription size, and cadence.
- Checks available balance in the Funding / Unified account before subscribing.
- Splits orders across strikes or tenors to spread execution risk.
- Includes a `--dry-run` / debug mode that prints the plan without hitting the
  order endpoint.

Use it when you want to accumulate a coin on dips without staring at charts.

### 2. `risk-parity-allocator`

**APR- and risk-adjusted allocator across Bybit Earn products.**

Bybit Earn spans Simple Earn, Fixed-Term, Liquidity Mining, and other yield
products with widely varying APRs and risk profiles. This skill:

- Pulls the current product catalog and their APR / lock-up / risk metadata.
- Computes a risk-parity weighting so each product contributes an equal share
  of portfolio risk (rather than equal capital).
- Emits a subscription plan sized to your available Earn balance.
- Supports category filters (e.g. "only Simple Earn + Fixed-Term stablecoins").

Use it when you want your Earn capital deployed across many products without
one high-APR-but-risky product dominating the portfolio.

### 3. `event-driven-doublewin`

**Volatility-hunting DoubleWin subscriber driven by macro & crypto news.**

DoubleWin is a Bybit structured product that pays out when the underlying moves
significantly in either direction inside a window. This skill:

- Scans economic-calendar feeds (CPI, FOMC, NFP, …) and crypto news.
- Passes candidate events to the AI agent for a rating: expected volatility,
  direction bias, confidence.
- For events that clear a configurable score threshold, sizes and submits a
  DoubleWin subscription targeted at the event window.
- Logs decisions so you can audit which events triggered which subscriptions.

Use it when you want to systematically buy volatility around scheduled events
instead of guessing direction.

## Installation

### Option A — Clone the whole repository

Drop the repo into your Claude skills directory so all three skills are picked
up at once:

```bash
git clone https://github.com/bybit-exchange/advanced-skills.git \
  ~/.claude/skills/advanced-skills
```

### Option B — Copy a single skill

Each top-level directory is self-contained. Copy just the one you need:

```bash
cp -r advanced-skills/dual-asset-buy-low ~/.claude/skills/
```

### Option C — Reference from an agent / plugin

Point your Claude Agent SDK application, MCP server, or custom plugin at the
individual skill directory. Skills follow the standard layout, so any loader
that reads `SKILL.md` frontmatter will discover them.

## Prerequisites

- **Python 3.11+** — the scripts use only the standard library plus `requests`.
- **A Bybit API key** with the scopes each skill requires. Read each skill's
  `SKILL.md` for the exact scopes — the allocator needs Earn read/write, the
  DCA and DoubleWin skills need Trade or Product-subscription scopes.
- Environment variables (set in your shell before invoking the agent):
  ```bash
  export BYBIT_API_KEY="..."
  export BYBIT_API_SECRET="..."
  export BYBIT_ENV="mainnet"   # or "testnet"
  ```

## Mandatory API headers

Every HTTP request the skills make to `api.bybit.com` or
`api-testnet.bybit.com` **must** include:

```
User-Agent: bybit-skill/1.3.0
X-Referer:  bybit-skill
```

The shared `bybit_client.py` in each skill sets these automatically. If you
extend a skill and add direct `curl` or `fetch` calls (e.g. for debugging),
you are responsible for setting both headers on those calls too. Requests
missing either header are considered non-compliant.

## Safety notes

- **Start on testnet.** All three skills default to `BYBIT_ENV=mainnet`, but
  every script accepts a `--testnet` flag / env override. Prove the workflow
  end-to-end on testnet before touching mainnet capital.
- **Dry-run first.** Each strategy script has a dry-run mode that prints the
  intended subscriptions / orders without submitting them. Use it after any
  change to config or thresholds.
- **The skills execute real trades.** They are automation tooling, not
  financial advice. You are responsible for position sizing, risk limits, and
  regulatory considerations in your jurisdiction.

## Development

### Local testing

Each skill's scripts can be executed directly for local iteration:

```bash
cd dual-asset-buy-low/scripts
python buy_low.py --dry-run --coin BTC --discount 0.05 --size 100
```

Please **do not** commit `__pycache__/` directories, macOS `.DS_Store` files,
or local state files (e.g. `*_trade_history.json`) generated by test runs.

### Adding a new skill

1. Create a new top-level directory `your-skill-name/`.
2. Add a `SKILL.md` with valid frontmatter (`name`, `description`, and any
   metadata you need — see the existing skills for the shape).
3. Put executable code under `scripts/` and any long-form API reference the
   agent might need under `reference/`.
4. Open a PR against `main`.

### Versioning

Each skill carries its own `version` in `SKILL.md` frontmatter and is bumped
independently. There is no repository-wide version.

## License

MIT — see individual skills' `SKILL.md` frontmatter for per-skill license
declarations.
