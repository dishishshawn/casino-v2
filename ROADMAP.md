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

## Funding-carry sleeve — BUILT & validated (2026-07-22)

Third disciplined hypothesis. Outcome: the best, most robust version yet, but STILL NO-GO.

- **Data solved.** Exchange live funding APIs cap at recent history (OKX ~3mo), so a real
  2021→2026 carry backtest was impossible from ccxt. Fix: `data/funding_dumps.py` pulls full
  funding from Binance's public data-dump CDN (`data.binance.vision`) — a SEPARATE domain
  reachable even though the Binance API is geo-blocked (451). ~6k rows/coin, cached under
  venue `binancevision`; `load_funding_panel` prefers it.
- **Naked carry is a dud** (Sharpe −0.07, −22% DD): a single directional perp leg carries too
  much price risk, which swamps the funding harvest. The real (delta-neutral cash-and-carry)
  edge needs a SPOT leg this engine doesn't model.
- **Cross-sectional market-neutral carry works** (short high-funding / long low-funding,
  demeaned each bar → strips market beta): standalone Sharpe **+0.50**, ~**0 correlation** to
  momentum. `signal.kind='combo'` runs an equal-risk momentum+carry blend.
- **Combo result:** fixes the 2025 headwind — **all 4 regimes now non-negative** (2025
  −0.14→+0.01), OOS holdout −0.07→**+0.14**, PBO 0.10→**0.086**. Stages 1–3 all PASS.
  **Still NO-GO: DSR 0.893 < 0.95.** Even a diversified, regime-robust book can't clear
  honest 20-trial deflation. Discipline held: did NOT tune the carry weight to force it.

## Where a legitimate GO could still come from (not yet attempted)

The momentum edge is real but sub-threshold; carry diversifies it but doesn't add enough
raw Sharpe. The remaining honest levers are ARCHITECTURAL, not tuning:

1. **Delta-neutral cash-and-carry** — add spot instruments and pair spot-long/perp-short to
   harvest funding with the price risk actually hedged. This is the *real* carry edge (vs the
   naked/cross-sectional approximations here) and could add meaningful uncorrelated Sharpe.
   Biggest change: the engine becomes multi-leg (spot + perp), not perp-only.
2. **Accept NO-GO.** Three disciplined iterations (turnover, breadth, carry) each improved the
   strategy and each was honestly validated; the engine still refuses to bless it. That is the
   system working as designed and matches the brutal base rate. No capital.

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
