"""Configuration loading.

Tariff episodes, product samples, country groups and estimation settings are all
configuration, never hard-coded logic. Adding a new tariff episode (Section 232,
2025 IEEPA actions, an EU retaliation list) is a YAML change plus a source
adapter, not a code change to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import CONFIG


@dataclass(slots=True)
class SampleConfig:
    """Which products, countries and months enter the analysis."""

    name: str
    description: str
    hs_level: str  # "HS6" or "HS10"
    hs6_products: list[str] = field(default_factory=list)
    hs2_chapters: list[str] = field(default_factory=list)
    treated_country_code: str = "5700"  # Census code for China
    comparison_country_codes: list[str] = field(default_factory=list)
    start_month: str = "2017-01"
    end_month: str = "2020-12"
    max_api_calls: int = 400


@dataclass(slots=True)
class EpisodeConfig:
    """A tariff episode: a set of actions treated as one policy experiment."""

    episode_id: str
    label: str
    imposing_country: str
    target_country_code: str
    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class EstimationConfig:
    event_window_pre: int = 12
    event_window_post: int = 12
    reference_event_time: int = -1
    cluster_on: list[str] = field(default_factory=lambda: ["hs6"])
    winsorize_unit_value_pct: float = 1.0
    min_pretreatment_months: int = 6
    ppml_max_iter: int = 200
    ppml_tol: float = 1e-9


@dataclass(slots=True)
class ProjectConfig:
    name: str
    sample: SampleConfig
    episodes: list[EpisodeConfig]
    estimation: EstimationConfig
    raw_bytes: bytes = b""
    source_path: Path | None = None

    @property
    def config_name(self) -> str:
        return self.source_path.name if self.source_path else self.name


def load_config(path: str | Path = "sample_slice.yaml") -> ProjectConfig:
    """Load a project configuration from ``config/``."""
    p = Path(path)
    if not p.is_absolute():
        p = CONFIG / p
    raw_bytes = p.read_bytes()
    doc = yaml.safe_load(raw_bytes)

    sample = SampleConfig(**doc["sample"])
    episodes = [EpisodeConfig(**e) for e in doc.get("episodes", [])]
    estimation = EstimationConfig(**doc.get("estimation", {}))
    return ProjectConfig(
        name=doc["name"],
        sample=sample,
        episodes=episodes,
        estimation=estimation,
        raw_bytes=raw_bytes,
        source_path=p,
    )
