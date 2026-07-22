# Roadmap & decisions

Living record of scope decisions so a fresh session has context without re-deriving it.
Newest decisions on top.

## Current status (2026-07-22)

- **Built & pushed:** cost-aware TSMOM research + validation engine (signal → risk/sizing
  → cost → backtest → validation gauntlet). 23 tests, ruff clean. Backtest-only.
- **First REAL-data gauntlet run is done.** Fetched from OKX (Binance/Bybit geo-blocked
  from this location: 451 / CloudFront 403). Verdict: **NO-GO** — and an honest one.
- **Next honest lever (recommended): a funding-carry sleeve.** Blocked only by data —
  see "Real-data findings" below.

## Real-data findings (2026-07-22)

Ran the gauntlet on genuine OKX hourly perp data, 2021→2026. Two disciplined,
economically-motivated hypothesis iterations (NOT parameter grinding), each validated once:

1. **Turnover was killing it.** Hourly rebalancing on a days-to-weeks signal bled
   ~4.5%/yr trade cost against a ~3%/yr gross return. Added a **daily rebalance throttle**
   (`risk.rebalance_hours`, default 24). Result: cost drag 4.47%→0.97%, net Sharpe
   0.53→0.74, and the OOS holdout flipped −0.16→+0.39. Gauntlet 1/4 → 3/4 stages.
2. **Breadth is the honest Sharpe lever.** Expanded 3→12 liquid large-cap OKX perps
   (chosen a-priori by market cap, not returns). Required an ingest fix: OKX returns an
   EMPTY batch when `since` predates a symbol's listing, so coins listed after 2021 were
   silently dropped — fixed with a forward-probe for the listing date. Result:
   **PBO 0.50→0.10** (config selection now robust), net Sharpe →0.95.

**Why it's still NO-GO (the real ceiling):** crypto TSMOM is **negative in the 2025→2026
regime**. That headwind shows up in BOTH the OOS holdout (Stage 2) and the latest walk-
forward regime (Stage 3), and it parks the **Deflated Sharpe at ~0.90, short of the 0.95
gate**. This is not a tuning problem — more coins / different lookbacks won't fix a genuine
regime headwind. Forcing GO from here (a regime filter fit to the failing window, or the
constant-rate funding fallback) would be exactly the overfitting the engine exists to catch.
The disciplined call: **NO-GO stands. No capital.**

**Known data caveat:** OKX funding-rate history is only ~3 months deep, so funding is
understated pre-2026 in the momentum backtest (drag was ~0, so low impact there) — but it
is a hard blocker for a carry sleeve, which needs multi-year funding history.

## Next hypothesis: funding-carry sleeve (orthogonal alpha)

The one remaining path to a *legitimate* GO. Carry (harvest rich perp funding) is
uncorrelated with trend and tends to do best in the choppy regimes where momentum bleeds —
i.e. it directly attacks the 2025+ weakness above. Downstream plumbing (sizing, cost model
with funding, gauntlet) already exists; a carry signal is a new `Signal` subclass.
**Hard prerequisite = DATA:** source multi-year funding history (a data vendor, or a
venue/endpoint with full depth). Until that lands, a carry backtest is impossible and must
not be faked with `default_funding_rate`. Sequence: get funding data → build carry `Signal`
→ validate carry alone → validate a momentum+carry portfolio through the same gauntlet.

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
