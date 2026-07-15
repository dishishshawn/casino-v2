"""Position sizing: vol-target base -> fractional Kelly -> correlation-aware
portfolio-vol scaling -> exposure caps.

Design-brief rules encoded here:
  * Fractional Kelly (quarter-to-half): the growth curve is flat near the optimum,
    so betting below Kelly costs little growth while sharply cutting drawdown, and
    it buffers estimation error (over-betting is far more dangerous than under-betting).
  * Volatility targeting to a modest portfolio vol.
  * Correlation-aware TOTAL risk: BTC/ETH are highly correlated, so we scale the
    whole weight vector by ex-ante portfolio vol from an EWMA covariance — NOT each
    leg independently. This stops correlated longs from stacking into hidden leverage.
  * Effective leverage cap (<=3x) and a per-position weight cap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from casino.risk import vol_target


def ewma_cov_scalers(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    halflife_bars: int,
    bars_per_year: int,
    target_annual_vol: float,
) -> pd.Series:
    """Per-bar scale factor s_t so ex-ante annualized portfolio vol hits the target.

    Uses an EWMA covariance of asset returns; predicted vol_t = sqrt(w_t' Σ_t w_t).
    Σ_t is computed from returns strictly before t (causal).
    """
    rets = np.log(prices.astype(float)).diff().fillna(0.0)
    cols = list(prices.columns)
    lam = 0.5 ** (1.0 / halflife_bars)
    n = len(cols)
    cov = np.zeros((n, n))
    mean = np.zeros(n)
    scalers = pd.Series(0.0, index=prices.index)
    r_arr = rets[cols].to_numpy()
    w_arr = weights.reindex(columns=cols).fillna(0.0).to_numpy()
    warm = max(2, halflife_bars // 2)
    for t in range(len(prices)):
        x = r_arr[t]
        # Update EWMA mean/cov with the CURRENT return AFTER using prior cov for t.
        w_t = w_arr[t]
        if t >= warm:
            port_var_bar = float(w_t @ cov @ w_t)
            port_vol_ann = np.sqrt(max(port_var_bar, 0.0) * bars_per_year)
            if port_vol_ann > 1e-9:
                scalers.iloc[t] = target_annual_vol / port_vol_ann
        # EWMA update (used by future bars only -> causal).
        delta = x - mean
        mean = mean + (1 - lam) * delta
        cov = lam * cov + (1 - lam) * np.outer(delta, x - mean)
    return scalers


def size(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    cfg: dict,
) -> pd.DataFrame:
    """Full sizing pipeline: scores + prices -> final target weight panel."""
    r = cfg["risk"]
    bars_per_year = int(r["bars_per_year"])
    hl = int(r["vol_forecast_halflife_hours"] * _bars_per_hour(cfg["data"]["timeframe"]))
    hl = max(2, hl)

    ann_vol = vol_target.forecast_annual_vol(prices, hl, bars_per_year)
    base = vol_target.inverse_vol_weights(scores, ann_vol, r["target_annual_vol"])

    # Fractional Kelly aggressiveness on the vol-targeted book.
    base = base * float(r["kelly_fraction"])

    # Correlation-aware portfolio-vol scaling (caps total correlated risk).
    scalers = ewma_cov_scalers(
        prices, base, hl, bars_per_year, r["target_annual_vol"]
    )
    # Never scale UP beyond 1x here (target is a ceiling, not a floor) to avoid
    # leveraging into a calm-vol estimate; also guards div-by-tiny-vol blowups.
    scalers = scalers.clip(upper=1.0)
    sized = base.mul(scalers, axis=0)

    # Per-position weight cap.
    sized = sized.clip(-r["max_position_weight"], r["max_position_weight"])

    # Gross leverage cap: shrink the whole row if sum|w| exceeds the cap.
    gross = sized.abs().sum(axis=1)
    lev_scale = (r["max_gross_leverage"] / gross).clip(upper=1.0).replace([np.inf, np.nan], 1.0)
    sized = sized.mul(lev_scale, axis=0)

    return sized.fillna(0.0)


def _bars_per_hour(timeframe: str) -> float:
    table = {"1m": 60, "5m": 12, "15m": 4, "1h": 1, "4h": 0.25, "1d": 1 / 24}
    return table[timeframe]
