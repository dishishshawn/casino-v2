"""Reconstructs the LIVE per-instrument target-weight panel for whatever
`signal.kind` the gauntlet validated -- the bridge from research signal to
tradable positions.

validation.gauntlet.strategy_returns only produces an aggregate RETURN
series (enough for the go/no-go verdict), not per-instrument weights, so it
can't drive order generation directly. This module mirrors its sleeve
dispatch and reuses `gauntlet.blend_scalers` (the exact same causal vol-
scaling formula) so the position panel actually traded has the same
economics as the backtested/validated strategy, not a reimplementation that
could silently drift from it.
"""

from __future__ import annotations

import pandas as pd

from casino.backtest import engine
from casino.costs.model import from_config as cost_from_config
from casino.risk import sizing
from casino.signals import carry, tsmom
from casino.validation.gauntlet import blend_scalers

# Sleeves this engine can express as an instrument-level weight panel. dn_carry
# and vrp model their sleeve as a return stream directly (no per-instrument
# position), so they aren't part of the current tradable GO and aren't
# supported here -- see ROADMAP.md.
_WEIGHT_SLEEVES = ("tsmom", "carry")


def _sleeve_weights(
    which: str, prices: pd.DataFrame, funding: pd.DataFrame | None, cfg: dict
) -> pd.DataFrame:
    if which == "carry":
        scores = carry.from_config(cfg, funding).scores(prices)
    elif which == "tsmom":
        scores = tsmom.from_config(cfg).scores(prices)
    else:
        raise ValueError(
            f"sleeve {which!r} has no instrument-level position panel in this "
            "engine (only tsmom/carry do) -- not part of the current tradable GO"
        )
    return sizing.size(scores, prices, cfg)


def target_weights(
    prices: pd.DataFrame, funding: pd.DataFrame | None, cfg: dict
) -> pd.DataFrame:
    """Per-instrument target weight panel for `cfg['signal']['kind']`."""
    kind = cfg.get("signal", {}).get("kind", "tsmom")

    if kind in _WEIGHT_SLEEVES:
        return _sleeve_weights(kind, prices, funding, cfg)

    if kind == "combo":
        w = float(cfg["signal"].get("combo_carry_weight", 0.5))
        w_mom = _sleeve_weights("tsmom", prices, funding, cfg)
        w_car = _sleeve_weights("carry", prices, funding, cfg)
        return (1.0 - w) * w_mom + w * w_car

    if kind == "blend":
        sleeves = cfg["signal"].get("sleeves", ["tsmom"])
        cm = cost_from_config(cfg)
        weight_panels = [_sleeve_weights(s, prices, funding, cfg) for s in sleeves]
        return_streams = [
            engine.run_backtest(prices, wp, cm, cfg, funding).net_returns
            for wp in weight_panels
        ]
        scalers = blend_scalers(return_streams, cfg)
        scaled = [wp.mul(sc, axis=0) for wp, sc in zip(weight_panels, scalers, strict=True)]
        total = scaled[0]
        for s in scaled[1:]:
            total = total.add(s)
        blended = total / len(scaled)
        # gauntlet.strategy_returns applies `scalers` at the RETURN-stream level,
        # where continuous drift is a free leverage adjustment. Reconstructed at
        # the WEIGHT level, that same continuous drift would force a fresh trade
        # on every instrument every bar -- costs the backtest never charged. Hold
        # it to the same rebalance grid as the underlying sleeves so what actually
        # gets traded matches the cadence (and cost) the gauntlet validated.
        return sizing.throttle_rebalance(blended, cfg)

    raise ValueError(f"execution book construction not supported for signal.kind={kind!r}")
