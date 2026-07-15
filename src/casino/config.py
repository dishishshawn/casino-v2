"""Config loading and reproducibility helpers.

The whole pipeline is config-driven so a run is fully described by (config, data
cache). We hash the resolved config so run outputs are traceable back to inputs —
the backtest-parity discipline the design brief calls for.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a YAML config, defaulting to config/default.yaml."""
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    cfg["_source_path"] = str(path)
    return cfg


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable short hash of a config (ignores private _-prefixed keys)."""
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    blob = json.dumps(clean, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]
