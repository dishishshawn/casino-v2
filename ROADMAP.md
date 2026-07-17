# Roadmap & decisions

Living record of scope decisions so a fresh session has context without re-deriving it.
Newest decisions on top.

## Current status (2026-07)

- **Built & pushed:** cost-aware TSMOM research + validation engine (signal → risk/sizing
  → cost → backtest → validation gauntlet). 23 tests, ruff clean. Backtest-only.
- **Not yet done:** a real-data gauntlet run. Blocked only by network egress in the web
  sandbox (default **Trusted** policy blocks exchange APIs — see `NETWORK.md`).
- **Last gauntlet result:** NO-GO on *synthetic* data (a pipeline exercise, not a real edge).

## Decisions

- **Jurisdiction: United States.** This constrains the eventual live venue (below).
- **Validate first, execution later.** No brokerage/API wiring until the gauntlet returns
  GO on real data for the *exact* variant to be traded. Matches the design brief's staged
  gate. The base rate is brutal (<1% of active traders profitable net of fees).
- **Robinhood execution is parked.** Investigated 2026-07. Reality for a US account:
  - Official **Crypto Trading API** = **spot only** (no leverage, no shorting, no perps).
  - **Agentic Trading MCP** = equities only in beta (long-only), crypto/options/**futures**
    "coming soon later in 2026". Trades sandboxed to a dedicated funded account.
  - Leveraged crypto **perps are EU-only**; not available to US accounts.
  - Robinhood **Gold** adds margin + Level II data, but no crypto leverage / stock shorting.
  - Net: no US Robinhood venue currently supports the brief's leveraged symmetric long/short
    strategy via API.

## Venue fork (decide after a real-data GO)

The engine is venue-agnostic on the research side; live execution is an adapter swap.

1. **Spot crypto, long/flat** via the official Robinhood Crypto Trading API — available now.
   Drops the short side and leverage; validate this *specific* variant before capital.
2. **CME micro futures** via Robinhood Futures — the brief's recommended "graduate venue":
   clean leverage, symmetric long/short, regulated/cleared. Best strategic fit; API is
   "coming soon" on the agentic roadmap. Preferred once its API lands.

## Immediate next step (needs an egress-enabled session)

```bash
python scripts/fetch_data.py        # real BTC/ETH/SOL/BNB/XRP perp history
python scripts/run_gauntlet.py      # real data -> GO / NO-GO (watch Stage 4: DSR + PBO)
```

If NO-GO: iterate the **hypothesis** (lookback family, add a funding-carry sleeve), not the
parameters. Then re-validate the exact variant the chosen venue can actually trade.

## Deferred (later phases)

Execution/OMS, maker/taker routing, regime kill-switch, monitoring/alerting, testnet paper
trading, live keys — all out of scope until validation passes. Keep exchange/broker keys off
ephemeral cloud sandboxes; run any live/paper stage on a host you control.
