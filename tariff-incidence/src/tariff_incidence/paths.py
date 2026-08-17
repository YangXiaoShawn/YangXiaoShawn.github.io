"""Canonical data-layer paths.

The project uses five strictly separated data layers:

    raw         Bytes exactly as retrieved from an official source. Never edited.
    staged      Parsed into tabular form, still source-shaped. No joins, no economics.
    normalized  Canonical schema, harmonised codes, validated types.
    analytical  Analysis-ready panels (product x country x month, exposure tables).
    results     Estimation output, tables, figures, generated report fragments.

Nothing downstream may write into an upstream layer.
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Repository root, overridable with TARIFF_PROJECT_ROOT (used by tests)."""
    env = os.environ.get("TARIFF_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


ROOT = project_root()

DATA = ROOT / "data"
RAW = DATA / "raw"
STAGED = DATA / "staged"
NORMALIZED = DATA / "normalized"
ANALYTICAL = DATA / "analytical"
RESULTS = DATA / "results"
MANIFESTS = DATA / "manifests"

CONFIG = ROOT / "config"
REPORTS = ROOT / "reports"
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"

_LAYERS = (RAW, STAGED, NORMALIZED, ANALYTICAL, RESULTS, MANIFESTS)


def ensure_layers() -> None:
    """Create the data-layer directories if they do not exist."""
    for p in _LAYERS:
        p.mkdir(parents=True, exist_ok=True)


def layer_path(layer: str, *parts: str) -> Path:
    """Resolve a path inside a named data layer, creating parent directories."""
    layers = {
        "raw": RAW,
        "staged": STAGED,
        "normalized": NORMALIZED,
        "analytical": ANALYTICAL,
        "results": RESULTS,
        "manifests": MANIFESTS,
    }
    if layer not in layers:
        raise ValueError(f"unknown data layer {layer!r}; expected one of {sorted(layers)}")
    p = layers[layer].joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
