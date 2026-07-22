# Roadmap & decisions

Living record of scope decisions so a fresh session has context without re-deriving it.
Newest decisions on top.

## Current status (2026-07-22)

- **Built & pushed:** cost-aware research + validation engine (signal → risk/sizing → cost
  → backtest → validation gauntlet). 37 tests, ruff clean. Backtest-only.
- **FIRST GO (marginal).** Strategy: **risk-parity blend of momentum + market-neutral carry**
  on real OKX 2021→2026 data. Clears all four gauntlet stages: net Sharpe 1.13, OOS holdout
  +0.64, 3/4 regimes positive, **DSR 0.9612 > 0.95, PBO 0.229**. `run_gauntlet.py` on the
  default config reproduces it. **This is a MARGINAL pass — next stage is PAPER TRADING, not
  capital.** See caveats below.
- Journey: single-sleeve momentum, breadth, both carry variants, delta-neutral carry, cross-
  sectional reversal, funding-positioning, and VRP timing were all NO-GO. The GO came from
  *portfolio construction* (causal risk-parity weighting) of the two sleeves that individually
  survived, not from a new signal.

## The GO — what it is and how much to trust it (2026-07-22)

- **Strategy:** `signal.kind='blend'`, `sleeves=['tsmom','carry']`, causal equal-risk
  (risk-parity) weighting (`blend_vol_hours=720`). Momentum = vol-targeted TSMOM; carry =
  cross-sectional market-neutral funding carry. Risk-parity down-weights whichever sleeve is
  currently high-vol (trailing, shifted → no lookahead). This lifted the fixed-50/50 combo's
  DSR 0.893 → 0.9612.
- **Robustness:** GO holds across blend windows 504–1440h (DSR 0.952–0.961); only 360h just
  misses (0.9465). Not a single-window fluke, but **marginal everywhere (~0.95–0.96)**.
- **TRUST IT ONLY PROVISIONALLY. Honest caveats:**
  1. **Marginal.** DSR barely clears 0.95. A thin edge, not a fat one.
  2. **Multiple-testing burden exceeds the 20-trial deflation.** Across the whole research
     program many strategies were explored; DSR deflates for 20 within-strategy trials, not
     the full search. The only real confirmation is genuinely OUT-OF-SAMPLE evidence →
     forward **paper trading** before any capital.
  3. **Survivorship bias** persists (12 currently-live OKX perps, `delisted_symbols` empty) —
     biases crypto momentum UPWARD. This alone could account for a marginal pass.
  4. **OKX-only, funding-data caveats** (momentum backtest funding understated pre-2026),
     no tail/liquidation modeling.

## VRP timing — explored, NO-GO (2026-07-22)

Pursued the two research-identified paid-data paths. **#1 OI/positioning: not reachable free**
(OKX caps ~6mo; Binance `metrics` dumps don't reach back; needs a paid vendor). **#2 VRP:
Deribit DVOL implied-vol index IS free and deep** (BTC/ETH, 2021-03→now) — better than the
research assumed. Built it (`data/dvol.py`, `backtest/vrp_timing.py`). Prototyped at Sharpe
1.25, but the gauntlet exposed it as fragile (PBO 0.73, OOS holdout negative) — another full-
sample mirage — and it HURTS the momentum+carry blend. VRP is a NO-GO; kept in-tree for research.

## Next step: PAPER TRADING the GO (not capital)

The gauntlet's own message on a GO: "proceed to the NEXT stage (paper trading). Still haircut
Sharpe." Per the design brief this is a DEFERRED, higher-risk phase that belongs on a host you
control, not an ephemeral sandbox, and needs execution/OMS wiring that is out of scope for this
research build. Before that: mitigate survivorship bias (populate `delisted_symbols`) and
re-confirm the GO, since that bias is the most likely source of a false marginal pass.

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

## ACCEPTED: perp-only directional strategy is NO-GO (2026-07-22)

Decision taken. Three disciplined iterations (turnover throttle, breadth to 12 coins,
market-neutral carry combo) each genuinely improved the strategy and each was honestly
validated — the combo even fixed the 2025 regime headwind — yet the engine still refused
to bless it (best DSR 0.893 < 0.95). That is the system working exactly as designed and it
matches the brutal base rate. **No capital on the perp-only strategy.**

## Delta-neutral cash-and-carry — BUILT & validated → ALSO NO-GO (2026-07-22)

Tried the one remaining architectural lever: the real basis trade (long spot + short perp,
price-hedged, harvest funding). Modeled the sleeve's return stream directly in
`backtest/delta_neutral.py` (perp-only engine can't hold two legs), with honest 2-leg costs
and a daily throttle. Validate via `signal.kind='dn_carry'`.

- **Full-sample Sharpe 3.72** (vol 0.65%) looked stellar — but the gauntlet exposed it as a
  mirage: **the entire edge is the 2021 bull-market funding bonanza.** OOS holdout Sharpe
  **−10.9**, two regimes negative (2022 bear, 2025), **DSR 0.0**. It does NOT generalize past
  its golden regime. Strong NO-GO.
- Caveat: the extreme Sharpe magnitudes are partly a per-bar measurement artifact (funding
  accrues smoothly, costs land on rebalance bars), but the in-sample→OOS **sign flip** is the
  robust result. And even this flattering model excludes the real killers — perp liquidation
  in a price spike, funding flips, exchange/counterparty risk (Oct-2025-style cascades).

## New-hypothesis research + prototypes (2026-07-22)

Ran a deep-research pass for genuinely new, engine-compatible hypotheses. Top two picks —
both buildable on reachable data (price + funding, all regimes), both meant to be
counter-cyclical to momentum:

1. **Cross-sectional short-horizon reversal** (long recent losers / short winners).
2. **Funding-positioning contrarian** (fade funding extremes; distinct from carry harvest).

**Both FAILED at the prototype stage** on our 12 liquid large-cap OKX perps (hourly, net of
costs) — no pulse, before even reaching the gauntlet:
- Reversal: negative Sharpe at EVERY horizon tested (6h→7d), demeaned or directional
  (−1.4 to −2.2). On liquid large-caps the cross-section is momentum-dominated; the reversal
  effect lives in small/illiquid coins we can't reach (the research flagged this exact caveat).
- Funding-positioning: negative Sharpe in every formulation (contrarian/with-funding ×
  cross-sectional/directional × 30d/60d windows), −0.35 to −1.9. The effect the practitioner
  blogs describe doesn't survive on large-caps net of costs.

Correlations to momentum were indeed negative as predicted, but a negative-Sharpe sleeve
can't help a blend (same lesson as naked carry). Disciplined call: did NOT grind more
price/funding formulations — the prototypes are decisively negative, not marginal.

## Conclusion: reachable free data is mined out for daily-frequency edges

This confirms the research's own "benchmark that changes everything": price + funding on
liquid large-caps has now been exhausted (momentum, breadth, both carry variants, reversal,
funding-positioning — all NO-GO). The only research-identified paths left require a **DATA
investment**, not another price-only signal:
- **Open-interest / positioning-divergence** — but free native OI history starts only ~2023
  (fails the 2021/2022 regime walk-forward). Needs paid history to 2020 (Tardis/Coinglass/
  Amberdata/CoinAPI).
- **Variance-risk-premium harvest** — needs an options / implied-vol feed (Deribit DVOL);
  can't be done cleanly perp-only.

Decision now belongs to the human: (a) fund a historical data source to unlock OI/positioning
or VRP, or (b) accept the honest terminal NO-GO on free data. No capital either way.

## Bottom line (updated)

Most variants were NO-GO — single-sleeve momentum, both carry variants standalone, delta-
neutral basis carry, reversal, funding-positioning, VRP timing. The **one GO** is the
**risk-parity blend of momentum + market-neutral carry** (DSR 0.9612, marginal), and it came
from *portfolio construction*, not a new signal. The engine did its job: it rejected every
overfit mirage (incl. a 3.72-Sharpe delta-neutral trade) and passed only a thin, robust-
across-windows edge. That GO advances to **paper trading**, not capital — and only after
survivorship bias is mitigated and the thin margin is re-confirmed out-of-sample.

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
