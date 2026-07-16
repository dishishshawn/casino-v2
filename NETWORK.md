# Network access for live data fetching

`scripts/fetch_data.py` pulls **public** OHLCV + funding history from crypto exchanges
via ccxt. This needs **no API keys**, but it does need outbound network access to the
exchange domains. Claude Code on the web sandboxes default to the **Trusted** network
policy, which allows package registries (pypi, npm, GitHub) but **blocks** exchange
APIs — you will see `NetworkError` / a proxy `403 CONNECT tunnel failed`.

To enable data fetching, give the environment a network policy that allows the venues.

## Configure the environment (works from mobile / iPhone)

1. Tap the **cloud icon** where you start a cloud session (environments are edited from
   the session / new-task screen — there is no separate Environments page).
2. Open the environment **for editing**.
3. In the **Network access** selector, choose **Custom** (recommended, least privilege)
   or **Full** (any domain, simplest but broadest).
4. For **Custom**, an **Allowed domains** field appears — one domain per line (below).
5. Check **"Also include default list of common package managers"** so pip/GitHub keep
   working.
6. Save, then start a **new** session — the policy is fixed per session, so an existing
   session will not pick up the change.

## Suggested allowlist (Custom)

Enter the venues you actually query. Wildcards cover subdomain surprises.

| Venue (ccxt id)               | Domains to allow                    |
| ----------------------------- | ----------------------------------- |
| Binance USD-M (`binanceusdm`) | `fapi.binance.com`, `*.binance.com` |
| Bybit (`bybit`)               | `api.bybit.com`, `*.bybit.com`      |
| OKX (`okx`)                   | `www.okx.com`, `*.okx.com`          |

```text
fapi.binance.com
*.binance.com
api.bybit.com
*.bybit.com
www.okx.com
*.okx.com
```

If a call still 403s, the security proxy keeps a DNS audit trail of requested
hostnames — check which host was blocked and add it.

## Verify it worked

```bash
python scripts/fetch_data.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --start 2021-01-01T00:00:00Z
python scripts/run_gauntlet.py        # real cached data, GO / NO-GO verdict
```

If egress is still blocked, everything runs offline with synthetic data
(`--synthetic`) — a pipeline exercise only, not a real edge.

## Important boundaries

- **Egress unlocks data, not trading.** This whole repo is backtest-only. Enabling
  egress only lets you download public market history.
- **Do not put exchange API keys in a cloud sandbox** — especially withdrawal-enabled
  keys. Live/paper execution is a deferred, higher-risk phase that belongs on a machine
  you control, not an ephemeral container.
- **Prefer Custom over Full.** An egress-open sandbox can reach anything; keep the
  allowlist to the venues you use.
- **Ephemeral containers can't hold live positions.** For any future live/paper stage,
  use an always-on host (a small VPS), not a phone-driven web session that sleeps.

Reference: https://code.claude.com/docs/en/claude-code-on-the-web#network-access
