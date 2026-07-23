# Execution architecture (paper trading, no keys)

Prep work for the roadmap's "paper trading" stage: the pieces that don't
depend on a real venue, built and tested now so connecting a real feed and
broker later is a small adapter swap, not a redesign. **Nothing in
`src/casino/execution/` makes a network call or reads an API key.**

## What's built

| Module | What it does |
|---|---|
| `execution/book.py` | Reconstructs the per-instrument target-weight panel for whatever `signal.kind` the gauntlet validated (tsmom / carry / combo / blend). This is the missing piece between the gauntlet's aggregate return verdict and an actual tradable position. |
| `execution/orders.py` | Diffs target weights against currently-held quantity -> discrete `OrderIntent`s. Skips dust-sized legs (`execution.min_trade_notional`). |
| `execution/broker.py` | The `Broker` Protocol -- the seam every venue adapter implements. Defined here so `book.py`/`orders.py`/`loop.py` never import anything venue-specific. |
| `execution/paper_broker.py` | A fully offline, in-memory `Broker` implementation. Fills instantly at the supplied mark price, charged with the *same* `CostModel` the backtest uses, so a paper run is directly comparable to a backtest. No network. |
| `execution/killswitch.py` | Halts new order generation on a drawdown breach or a stalled data feed. Does **not** flatten positions itself -- that's a venue-specific, logged action that belongs with a real broker adapter. |
| `execution/loop.py` | One decision tick: mark-to-market -> kill-switch check -> diff target weights against held positions -> submit. `run_replay` drives it over a cached historical panel for an end-to-end offline smoke test. |
| `scripts/run_paper.py` | CLI entry point: `python scripts/run_paper.py --synthetic` (or against real cached data once fetched) runs the whole pipeline and prints fills/positions/equity. |

## What this is NOT

- **Not connected to any exchange.** `run_paper.py` only replays the cached
  Parquet panel through `PaperBroker`. It's a dry-run of the *decision*
  pipeline (signal -> weights -> orders -> simulated fills), not a live
  system.
- **Not a change to the GO/NO-GO verdict.** Building this doesn't make the
  strategy tradable — see ROADMAP.md for the gauntlet re-run still pending
  the survivorship-bias fix.
- **Not where live/real paper trading should run.** Per NETWORK.md and the
  design brief: that phase belongs on a host you control (a small always-on
  VPS), never an ephemeral cloud sandbox. **Do not add exchange or broker API
  keys to this repo or this environment**, even read-only/testnet keys.

## A subtlety worth knowing: why weights are throttled before trading

`validation.gauntlet.strategy_returns` computes the `blend` strategy's
risk-parity mix at the *return-stream* level: each sleeve's net return series
is scaled by a continuously-drifting causal vol scalar, then averaged. That
scaling is economically free in a returns-based backtest — it's a leverage
adjustment, not a new position.

Reconstructed at the *instrument-weight* level (what `book.py` has to do to
produce tradable orders), that same continuous scalar drift would force a
fresh trade on every instrument, every bar — a cost the backtest never
charged. `book.py` throttles the final blended panel onto the same
`risk.rebalance_hours` grid the underlying sleeves already use, and
`loop.run_replay` only generates orders on bars where the weight value
actually changed (matching `costs.model.CostModel`'s own turnover accounting,
which is silent between explicit weight changes). This keeps what actually
gets traded consistent with what the gauntlet validated. See
`test_target_weights_blend_matches_gauntlet_return_economics` in
`tests/test_execution.py` for the regression check.

## Try it now (offline, no network)

```bash
python scripts/run_paper.py --synthetic --synthetic-bars 3000
```

Once real data is fetched (an egress-enabled session — see NETWORK.md):

```bash
python scripts/fetch_data.py
python scripts/run_paper.py
```

## What's still deferred

- **A real `Broker` implementation.** Implement the `Broker` Protocol against
  an exchange testnet/demo account (or the eventual regulated-futures API —
  see ROADMAP.md's venue fork) on a host you control. `paper_broker.py`'s
  interface is the contract to match.
- **A live/near-real-time `DataFeed`.** `loop.run_replay` consumes a static
  cached panel; a live loop needs a feed that appends new bars and calls
  `run_tick` per bar (or per poll interval), still with no keys required for
  public market data.
- **Maker/taker order routing, position-flattening on kill-switch, alerting
  (Slack/email/etc).** Still out of scope — noted here so they're not
  silently assumed to exist.
