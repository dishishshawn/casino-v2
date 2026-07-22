"""The staged validation gauntlet — the project's real moat.

Runs the design brief's go/no-go gate end to end:
  Stage 1  in-sample with full costs      (reject if the edge can't clear costs)
  Stage 2  untouched OOS holdout          (reject if it doesn't generalize)
  Stage 3  walk-forward across regimes    (must not depend on one regime)
  Stage 4  CPCV -> DSR + PBO              (multiple-testing-corrected go/no-go)

The verdict is GO only if the Deflated Sharpe is clearly significant (DSR > 0.95)
AND the Probability of Backtest Overfitting is below the configured ceiling AND the
strategy survived costs and generalized. Otherwise: iterate the HYPOTHESIS, not the
parameters.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from casino.backtest import engine, metrics
from casino.costs.model import CostModel
from casino.costs.model import from_config as cost_from_config
from casino.risk import sizing
from casino.signals import carry, tsmom
from casino.validation import cpcv, deflated_sharpe


def _sleeve_returns(
    which: str,
    prices: pd.DataFrame,
    funding: pd.DataFrame | None,
    cfg: dict,
    cm: CostModel,
) -> pd.Series:
    """Net return series for a single sleeve ('tsmom' or 'carry')."""
    if which == "carry":
        scores = carry.from_config(cfg, funding).scores(prices)
    else:
        scores = tsmom.from_config(cfg).scores(prices)
    weights = sizing.size(scores, prices, cfg)
    return engine.run_backtest(prices, weights, cm, cfg, funding).net_returns


def strategy_returns(
    prices: pd.DataFrame,
    funding: pd.DataFrame | None,
    cfg: dict,
    cost_model: CostModel | None = None,
) -> pd.Series:
    """Net per-bar return series for one config over the whole sample.

    `signal.kind` selects the strategy:
      * 'tsmom' (default) — time-series momentum only.
      * 'carry'           — funding-carry sleeve only.
      * 'combo'           — equal-risk blend of momentum + carry sleeves. The two
                            sleeves are vol-targeted to the same level, so an equal
                            weight is ~equal-risk (an a-priori choice, not tuned).
    """
    cm = cost_model if cost_model is not None else cost_from_config(cfg)
    kind = cfg.get("signal", {}).get("kind", "tsmom")
    if kind == "carry":
        return _sleeve_returns("carry", prices, funding, cfg, cm)
    if kind == "combo":
        w = float(cfg["signal"].get("combo_carry_weight", 0.5))
        r_mom = _sleeve_returns("tsmom", prices, funding, cfg, cm)
        r_car = _sleeve_returns("carry", prices, funding, cfg, cm)
        return ((1.0 - w) * r_mom + w * r_car).rename("net")
    return _sleeve_returns("tsmom", prices, funding, cfg, cm)


def _candidate_configs(cfg: dict) -> list[dict]:
    """Grid of TSMOM variants for multiple-testing / PBO analysis (honest trials)."""
    base_lbs = cfg["signal"]["lookbacks_hours"]
    lb_sets = [
        [base_lbs[0]],
        [base_lbs[-1]],
        base_lbs[:2],
        base_lbs[2:] if len(base_lbs) > 2 else base_lbs,
        base_lbs,
    ]
    kellys = [0.25, 0.35, 0.5]
    n_trials = int(cfg["validation"]["n_trials"])
    out = []
    for lbs, k in itertools.product(lb_sets, kellys):
        c = _clone(cfg)
        c["signal"]["lookbacks_hours"] = lbs
        c["risk"]["kelly_fraction"] = k
        out.append(c)
        if len(out) >= n_trials:
            return out
    return out


def _clone(cfg: dict) -> dict:
    import copy

    return copy.deepcopy(cfg)


def candidate_returns_matrix(
    prices: pd.DataFrame, funding: pd.DataFrame | None, cfg: dict
) -> pd.DataFrame:
    """T x M matrix of net returns across candidate configs (for PBO + DSR variance)."""
    cols = {}
    for i, c in enumerate(_candidate_configs(cfg)):
        cols[f"cfg{i}"] = strategy_returns(prices, funding, c)
    return pd.DataFrame(cols).dropna(how="all")


@dataclass
class StageResult:
    name: str
    passed: bool
    detail: dict = field(default_factory=dict)


@dataclass
class GauntletReport:
    stages: list[StageResult]
    verdict: str  # "GO" or "NO-GO"

    def format(self) -> str:
        lines = ["\n================  VALIDATION GAUNTLET  ================"]
        for s in self.stages:
            flag = "PASS" if s.passed else "FAIL"
            lines.append(f"[{flag}] {s.name}")
            for k, v in s.detail.items():
                lines.append(f"         {k}: {v}")
        lines.append("------------------------------------------------------")
        lines.append(f"VERDICT: {self.verdict}")
        if self.verdict == "NO-GO":
            lines.append("  -> iterate the HYPOTHESIS, not the parameters. No capital.")
        else:
            lines.append("  -> proceed to the NEXT stage (paper trading). Still haircut Sharpe.")
        lines.append("======================================================")
        return "\n".join(lines)


def run_gauntlet(
    prices: pd.DataFrame,
    funding: pd.DataFrame | None,
    cfg: dict,
) -> GauntletReport:
    bpy = int(cfg["risk"]["bars_per_year"])
    v = cfg["validation"]
    stages: list[StageResult] = []

    # ---- Stage 1: in-sample, full costs vs no costs (must clear costs) ----
    r_full = strategy_returns(prices, funding, cfg)
    zero_cm = CostModel(0, 0, 0, 0, cfg["costs"]["funding_interval_hours"], 0.0)
    r_gross = strategy_returns(prices, funding, cfg, cost_model=zero_cm)
    sr_full = metrics.sharpe_ratio(r_full, bpy)
    sr_gross = metrics.sharpe_ratio(r_gross, bpy)
    s1 = StageResult(
        "Stage 1: in-sample clears costs",
        passed=sr_full > 0,
        detail={
            "sharpe_gross": round(sr_gross, 3),
            "sharpe_net": round(sr_full, 3),
            "cost_haircut": round(sr_gross - sr_full, 3),
        },
    )
    stages.append(s1)

    # ---- Stage 2: untouched OOS holdout ----
    n = len(r_full)
    cut = int(n * (1 - cfg["backtest"]["oos_holdout_frac"]))
    is_sr = metrics.sharpe_ratio(r_full.iloc[:cut], bpy)
    oos_sr = metrics.sharpe_ratio(r_full.iloc[cut:], bpy)
    s2 = StageResult(
        "Stage 2: OOS holdout generalizes",
        passed=oos_sr > 0,
        detail={"in_sample_sharpe": round(is_sr, 3), "holdout_sharpe": round(oos_sr, 3)},
    )
    stages.append(s2)

    # ---- Stage 3: walk-forward across regimes ----
    regime_srs = {}
    for reg in v["regimes"]:
        seg = r_full.loc[str(reg["start"]):str(reg["end"])]
        regime_srs[reg["name"]] = round(metrics.sharpe_ratio(seg, bpy), 3) if len(seg) > 10 else None
    valid = [x for x in regime_srs.values() if x is not None]
    # Robust if it is not negative in more than one regime.
    n_neg = sum(1 for x in valid if x < 0)
    s3 = StageResult(
        "Stage 3: walk-forward across regimes",
        passed=(len(valid) >= 2 and n_neg <= 1),
        detail={"regime_sharpes": regime_srs, "regimes_negative": n_neg},
    )
    stages.append(s3)

    # ---- Stage 4: CPCV -> DSR + PBO ----
    label_h = int(v["label_horizon_bars"])
    embargo = max(1, int(len(r_full) * v["embargo_frac"]))
    oos_dist = cpcv.oos_sharpe_distribution(
        r_full, v["cpcv_n_groups"], v["cpcv_k_test"], label_h, embargo
    )  # per-observation SR per test block

    matrix = candidate_returns_matrix(prices, funding, cfg)
    pbo = cpcv.probability_of_backtest_overfitting(matrix, n_partitions=v["cpcv_n_groups"])

    # DSR on the primary config, deflated by the trial grid's SR spread.
    sr_obs = r_full.dropna().mean() / r_full.dropna().std(ddof=1) if r_full.std(ddof=1) > 0 else 0.0
    from scipy import stats as _st

    skew = float(_st.skew(r_full.dropna()))
    kurt = float(_st.kurtosis(r_full.dropna(), fisher=False))  # non-excess
    cand_srs = np.array([cpcv._sharpe(matrix[c].dropna().to_numpy()) for c in matrix.columns])
    sr_var = float(np.var(cand_srs, ddof=1)) if len(cand_srs) > 1 else 1e-6
    dsr = deflated_sharpe.deflated_sharpe_ratio(
        sr_obs, len(r_full.dropna()), skew, kurt, int(v["n_trials"]), sr_var
    )

    dsr_ok = dsr > 0.95
    pbo_ok = (not np.isnan(pbo)) and pbo <= v["max_pbo"]
    s4 = StageResult(
        "Stage 4: CPCV DSR + PBO gate",
        passed=dsr_ok and pbo_ok,
        detail={
            "oos_sharpe_median_ann": round(float(np.median(oos_dist)) * np.sqrt(bpy), 3),
            "oos_sharpe_paths": len(oos_dist),
            "deflated_sharpe_prob": round(dsr, 4),
            "pbo": round(pbo, 4) if not np.isnan(pbo) else "n/a",
            "n_trials_deflated": int(v["n_trials"]),
        },
    )
    stages.append(s4)

    verdict = "GO" if all(s.passed for s in stages) else "NO-GO"
    return GauntletReport(stages=stages, verdict=verdict)
