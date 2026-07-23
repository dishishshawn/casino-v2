# casino-v2

**A cost-aware TSMOM research + validation engine for crypto perpetual futures.**

This is the **research/backtest** stage of the system described in
`HighRisk_Directional_Trading_Bot` design brief. Its entire purpose is to answer one
honest question and gate on the answer:

> Does vol-targeted, fractional-Kelly time-series momentum on liquid crypto perps have
> an edge that survives realistic costs **and** multiple-testing correction?

Per the brief, the real moat is **not** signal cleverness — it is the anti-overfitting
**validation gauntlet** and disciplined **risk plumbing**. This build implements both.
**No live or paper order routing, no API keys, no capital is deployed.** The only
deliverable is a `GO` / `NO-GO` verdict.

> ⚠️ The base rate is brutal: <1% of day traders are reliably profitable net of fees.
> Assume you will fail; engineer to survive long enough to learn. Never risk capital
> you can't lose.

## Architecture

Modular (signal → risk/sizing → cost → backtest → validation) so execution, a
regime kill-switch, and monitoring can be added later without touching research code.

| Module | What it does | Brief anchor |
|---|---|---|
| `data/` | ccxt OHLCV + funding → Parquet cache; survivorship-bias handling | cheap data, delisted-coin hazard |
| `signals/tsmom.py` | Time-series momentum, **short crypto lookbacks**, long/short symmetric, vol-normalized, causal | Moskowitz-Ooi-Pedersen (2012); crypto favors shorter lookbacks |
| `costs/model.py` | Taker fee + half-spread + **turnover-scaled adverse slippage** + **funding** | momentum *pays* slippage; costs flip backtests |
| `risk/` | Vol targeting → **fractional (¼–½) Kelly** → correlation-aware portfolio-vol cap → ≤3× leverage | fractional Kelly; BTC/ETH sized together |
| `backtest/` | Returns-based sim with exact costs+funding; metrics incl. **50% Sharpe haircut** | haircut backtested Sharpe ~50% |
| `validation/` | Purge+embargo, CPCV, **Deflated Sharpe + PBO**, staged gauntlet | López de Prado / Bailey; the moat |
| `execution/` | Target-weight reconstruction, order diffing, offline paper broker, kill-switch — **no network, no keys** | see EXECUTION.md |

### Why returns-based (not vectorbt end-to-end)?
Perp **funding** and turnover-scaled adverse slippage aren't modeled natively by
vectorbt, and the brief insists both be exact. So the research engine is a transparent
returns simulator; **vectorbt is used as an independent cross-check** of the gross
price accounting (`backtest.engine.vbt_check`, asserted in `tests/test_backtest_vbt.py`).

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
# 1. Fetch real data (requires network egress to the exchange — see note below)
python scripts/fetch_data.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --start 2021-01-01T00:00:00Z

# 2. Run a single cost-aware backtest -> metrics table + equity plot in reports/
python scripts/run_backtest.py                 # real cached data
python scripts/run_backtest.py --synthetic     # offline synthetic data
python scripts/run_backtest.py --synthetic --no-costs   # sanity: costs must bite

# 3. Run the staged validation gauntlet -> GO / NO-GO verdict
python scripts/run_gauntlet.py --synthetic

# 4. Offline dry-run of the paper-trading decision pipeline (no network/keys)
python scripts/run_paper.py --synthetic
```

See [EXECUTION.md](EXECUTION.md) for what the paper-trading architecture is
(and deliberately is not) before running step 4.

### The validation gauntlet (go/no-go gate)
1. **In-sample, full costs** — reject if the edge can't clear costs.
2. **Untouched OOS holdout** — reject if it doesn't generalize.
3. **Walk-forward across regimes** — must not depend on a single regime.
4. **CPCV → Deflated Sharpe + PBO** — `GO` only if `DSR > 0.95` **and** `PBO ≤ max_pbo`.

If `NO-GO`: iterate the **hypothesis**, not the parameters.

## Configuration

All knobs live in `config/default.yaml`: universe, TSMOM lookbacks, cost params,
vol target, Kelly fraction, leverage caps, CPCV/DSR settings, and regime windows.
Runs are hashed (`casino.config.config_hash`) for reproducibility.

## Known limitations (called out honestly)

- **Survivorship bias.** ccxt lists only currently-live perps, which biases crypto
  momentum **upward** — the single most common way crypto backtests mislead.
  `config.data.delisted_symbols` now carries two real, well-documented delistings
  (FTT, LUNA — see ROADMAP.md) fetched via `data/price_dumps.py`'s static-archive
  fallback, but this is a partial mitigation, not exhaustive; a rigorous fix needs
  a paid delisted-coin database. The loud warning only fires when the list is empty.
- **Network egress.** Live data fetch requires an environment whose egress policy
  allows the exchange domains (Binance/Bybit/OKX). Where that is blocked, use
  `--synthetic` to exercise the full pipeline offline. Synthetic mode is a pipeline
  test **only** — it is not a real edge. See [NETWORK.md](NETWORK.md) for the exact
  allowlist and mobile setup steps.
- **Deferred (later phases).** `execution/` now has the venue-agnostic target-weight
  reconstruction, order diffing, an offline paper broker, and a kill-switch (see
  EXECUTION.md) — but maker/taker routing, a real broker/testnet adapter, a live
  data feed, monitoring/alerting, and live keys are still out of scope, and no
  capital or real order routing is connected anywhere in this build.

## Tests

```bash
pytest          # cost monotonicity, vol/leverage caps, no-leakage purging,
                # DSR shrinks with trials, PBO high on noise / low on a real edge,
                # signal captures momentum & shuffling destroys it, vectorbt cross-check,
                # execution book/orders/paper-broker/kill-switch
ruff check src scripts tests
```
