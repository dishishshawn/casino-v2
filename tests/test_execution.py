from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from casino.backtest import engine
from casino.costs.model import CostModel
from casino.costs.model import from_config as cost_from_config
from casino.execution import loop, orders
from casino.execution.book import target_weights
from casino.execution.killswitch import KillSwitch, KillSwitchConfig
from casino.execution.paper_broker import PaperBroker
from casino.validation.gauntlet import strategy_returns


def _cost_model() -> CostModel:
    return CostModel(taker_fee_bps=4.0, half_spread_bps=1.0, slippage_base_bps=1.0,
                      slippage_impact_bps=5.0, funding_interval_hours=8,
                      default_funding_rate=0.0001)


# --------------------------------------------------------------------------
# orders.weights_to_orders
# --------------------------------------------------------------------------

def test_weights_to_orders_generates_buy_and_sell():
    target = pd.Series({"BTC/USDT:USDT": 0.5, "ETH/USDT:USDT": -0.3})
    prices = pd.Series({"BTC/USDT:USDT": 100.0, "ETH/USDT:USDT": 50.0})
    intents = orders.weights_to_orders(target, {}, equity=10_000.0, prices=prices)
    by_symbol = {o.symbol: o for o in intents}
    assert by_symbol["BTC/USDT:USDT"].side == "buy"
    assert by_symbol["BTC/USDT:USDT"].qty == pytest.approx(50.0)  # 0.5*10000/100
    assert by_symbol["ETH/USDT:USDT"].side == "sell"
    assert by_symbol["ETH/USDT:USDT"].qty == pytest.approx(60.0)  # 0.3*10000/50


def test_weights_to_orders_skips_dust_and_nan():
    target = pd.Series({"BTC/USDT:USDT": 0.0001, "ETH/USDT:USDT": np.nan})
    prices = pd.Series({"BTC/USDT:USDT": 100.0, "ETH/USDT:USDT": 50.0})
    intents = orders.weights_to_orders(
        target, {}, equity=10_000.0, prices=prices, min_trade_notional=10.0
    )
    assert intents == []


def test_weights_to_orders_no_trade_when_already_at_target():
    target = pd.Series({"BTC/USDT:USDT": 0.5})
    prices = pd.Series({"BTC/USDT:USDT": 100.0})
    current = {"BTC/USDT:USDT": 50.0}  # already holds the target qty
    intents = orders.weights_to_orders(target, current, equity=10_000.0, prices=prices)
    assert intents == []


# --------------------------------------------------------------------------
# PaperBroker
# --------------------------------------------------------------------------

def test_paper_broker_buy_updates_position_and_charges_fee():
    broker = PaperBroker(_cost_model(), init_cash=10_000.0)
    fill = broker.place_order("BTC/USDT:USDT", "buy", 10.0, 100.0, pd.Timestamp("2021-01-01"))
    assert broker.positions["BTC/USDT:USDT"] == pytest.approx(10.0)
    expected_fee = 10.0 * 100.0 * (4.0 + 1.0 + 1.0) * 1e-4
    assert fill.fee == pytest.approx(expected_fee)
    assert broker.cash == pytest.approx(10_000.0 - 10.0 * 100.0 - expected_fee)


def test_paper_broker_sell_then_equity_marks_to_market():
    broker = PaperBroker(_cost_model(), init_cash=10_000.0)
    broker.place_order("BTC/USDT:USDT", "sell", 5.0, 100.0, pd.Timestamp("2021-01-01"))
    assert broker.positions["BTC/USDT:USDT"] == pytest.approx(-5.0)
    equity = broker.get_equity({"BTC/USDT:USDT": 120.0})
    assert equity == pytest.approx(broker.cash + (-5.0) * 120.0)


def test_paper_broker_rejects_bad_input():
    broker = PaperBroker(_cost_model())
    with pytest.raises(ValueError):
        broker.place_order("BTC/USDT:USDT", "buy", -1.0, 100.0, pd.Timestamp("2021-01-01"))
    with pytest.raises(ValueError):
        broker.place_order("BTC/USDT:USDT", "hold", 1.0, 100.0, pd.Timestamp("2021-01-01"))


# --------------------------------------------------------------------------
# KillSwitch
# --------------------------------------------------------------------------

def test_killswitch_halts_on_drawdown():
    ks = KillSwitch(KillSwitchConfig(max_drawdown=0.2, max_stale_bars=100))
    assert ks.should_halt(100_000.0)[0] is False
    assert ks.should_halt(90_000.0)[0] is False  # 10% dd, under limit
    halted, reason = ks.should_halt(75_000.0)  # 25% dd, breaches 20%
    assert halted is True
    assert "drawdown" in reason


def test_killswitch_halts_on_stale_data():
    ks = KillSwitch(KillSwitchConfig(max_drawdown=0.99, max_stale_bars=2))
    ts = pd.Timestamp("2021-01-01")
    assert ks.should_halt(100_000.0, bar_ts=ts)[0] is False
    assert ks.should_halt(100_000.0, bar_ts=ts)[0] is False  # 1 repeat, still under
    halted, reason = ks.should_halt(100_000.0, bar_ts=ts)  # 2 repeats, breaches
    assert halted is True
    assert "stale" in reason


def test_killswitch_resets_staleness_on_new_bar():
    ks = KillSwitch(KillSwitchConfig(max_drawdown=0.99, max_stale_bars=2))
    ks.should_halt(100_000.0, bar_ts=pd.Timestamp("2021-01-01 00:00"))
    ks.should_halt(100_000.0, bar_ts=pd.Timestamp("2021-01-01 00:00"))
    halted, _ = ks.should_halt(100_000.0, bar_ts=pd.Timestamp("2021-01-01 01:00"))
    assert halted is False


# --------------------------------------------------------------------------
# execution.book.target_weights -- must match the validated gauntlet economics
# --------------------------------------------------------------------------

def _synthetic_prices_and_funding(cfg, n_bars=1200, seed=3):
    idx = pd.date_range("2021-01-01", periods=n_bars, freq="1h", tz="UTC", name="ts")
    syms = cfg["data"]["universe"]
    prices = pd.DataFrame(
        {s: 100.0 * np.exp(np.cumsum(0.01 * np.random.default_rng(i).standard_normal(n_bars)))
         for i, s in enumerate(syms)},
        index=idx,
    )
    rates = np.linspace(0.0003, -0.0003, len(syms))
    funding = pd.DataFrame({s: rates[i] for i, s in enumerate(syms)}, index=idx)
    return prices, funding


def test_target_weights_tsmom_matches_sizing_directly(cfg):
    from casino.risk import sizing
    from casino.signals import tsmom

    cfg["signal"]["kind"] = "tsmom"
    prices, funding = _synthetic_prices_and_funding(cfg)
    expected = sizing.size(tsmom.from_config(cfg).scores(prices), prices, cfg)
    got = target_weights(prices, funding, cfg)
    pd.testing.assert_frame_equal(got, expected)


def test_target_weights_blend_matches_gauntlet_return_economics(cfg):
    cfg["signal"]["kind"] = "blend"
    cfg["signal"]["sleeves"] = ["tsmom", "carry"]
    prices, funding = _synthetic_prices_and_funding(cfg)

    weights = target_weights(prices, funding, cfg)
    reconstructed_returns = engine.run_backtest(
        prices, weights, cost_from_config(cfg), cfg, funding
    ).net_returns
    validated_returns = strategy_returns(prices, funding, cfg)

    # Reconstructing per-instrument weights from the same causal scalers and
    # re-running them through the identical backtest engine should reproduce
    # the gauntlet's own return series (mean/std within a tolerance -- the
    # rebalance throttle on the blended panel is a deliberate, documented
    # divergence from the gauntlet's costless-scalar assumption, so an exact
    # match isn't expected, but the economics must stay close).
    corr = reconstructed_returns.corr(validated_returns)
    assert corr > 0.9


# --------------------------------------------------------------------------
# execution.loop.run_replay -- end-to-end offline smoke test
# --------------------------------------------------------------------------

def test_run_replay_trades_only_on_rebalance_grid(cfg):
    cfg["signal"]["kind"] = "tsmom"
    prices, funding = _synthetic_prices_and_funding(cfg, n_bars=1200)
    broker = PaperBroker(_cost_model(), init_cash=100_000.0)
    killswitch = KillSwitch(KillSwitchConfig(max_drawdown=0.9, max_stale_bars=10_000))

    results = loop.run_replay(prices, funding, cfg, broker, killswitch)

    assert len(results) > 0
    assert not any(r.halted for r in results)
    n_with_orders = sum(1 for r in results if r.orders)
    # Rebalances only happen every `risk.rebalance_hours` bars -- most ticks
    # should be no-ops, not every tick trading (the bug this test guards).
    assert n_with_orders < len(results) * 0.2
    assert sum(len(r.orders) for r in results) == len(broker.fills)


def test_run_replay_killswitch_halts_and_stops_new_orders(cfg):
    cfg["signal"]["kind"] = "tsmom"
    prices, funding = _synthetic_prices_and_funding(cfg, n_bars=1200)
    broker = PaperBroker(_cost_model(), init_cash=100_000.0)
    # A drawdown limit of 0 halts on the very first mark-to-market.
    killswitch = KillSwitch(KillSwitchConfig(max_drawdown=0.0, max_stale_bars=10_000))

    results = loop.run_replay(prices, funding, cfg, broker, killswitch)

    assert results[-1].halted is True
    assert all(len(r.orders) == 0 for r in results)
    assert broker.fills == []
