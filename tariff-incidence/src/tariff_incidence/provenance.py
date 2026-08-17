"""Provenance stamping.

Acceptance criterion 15 requires every result to record its data period,
configuration, and Git commit. Everything that writes to ``data/results`` must
attach a :class:`RunStamp`.

Criterion 17 (no unsupported causal claim) is supported mechanically by
:class:`DataProvenance`: any artefact built from the synthetic pipeline-validation
generator is tagged ``SYNTHETIC_PIPELINE_VALIDATION`` and the reporting layer
refuses to describe such numbers as empirical estimates.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .paths import ROOT


class DataProvenance(str, Enum):
    """Where the numbers in an artefact ultimately came from."""

    OFFICIAL = "OFFICIAL"
    """Every input traces to an official statistical or legal source."""

    SYNTHETIC_PIPELINE_VALIDATION = "SYNTHETIC_PIPELINE_VALIDATION"
    """Inputs (or some of them) come from the documented synthetic generator.

    Numbers carrying this tag validate that the code path runs and recovers a
    known ground truth. They are NOT evidence about the world and must never be
    reported as empirical findings.
    """

    MIXED = "MIXED"
    """Official policy/structure inputs combined with synthetic trade flows."""

    @property
    def is_empirical(self) -> bool:
        return self is DataProvenance.OFFICIAL


def git_commit() -> str:
    """Short Git commit of the working tree, or a marker when unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode != 0:
            return "NO_COMMIT"
        commit = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "NO_GIT"

    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return f"{commit}-dirty" if dirty.stdout.strip() else commit


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class RunStamp:
    """Identifies the exact conditions under which a result was produced."""

    run_id: str
    created_utc: str
    git_commit: str
    config_name: str
    config_sha256: str
    data_provenance: DataProvenance
    data_period_start: str | None = None
    data_period_end: str | None = None
    python_version: str = field(default_factory=platform.python_version)
    platform: str = field(default_factory=platform.platform)
    notes: str = ""

    @classmethod
    def create(
        cls,
        config_name: str,
        config_bytes: bytes,
        data_provenance: DataProvenance,
        data_period_start: str | None = None,
        data_period_end: str | None = None,
        notes: str = "",
    ) -> RunStamp:
        now = datetime.now(UTC)
        cfg_hash = sha256_bytes(config_bytes)
        run_id = f"{now:%Y%m%dT%H%M%SZ}-{cfg_hash[:8]}"
        return cls(
            run_id=run_id,
            created_utc=now.isoformat(),
            git_commit=git_commit(),
            config_name=config_name,
            config_sha256=cfg_hash,
            data_provenance=data_provenance,
            data_period_start=data_period_start,
            data_period_end=data_period_end,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_provenance"] = self.data_provenance.value
        return d

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    def banner(self) -> str:
        """Human-readable provenance banner for the top of generated reports."""
        if self.data_provenance.is_empirical:
            head = "DATA PROVENANCE: OFFICIAL SOURCES"
            body = "All figures below derive from official statistical or legal sources."
        elif self.data_provenance is DataProvenance.MIXED:
            head = "DATA PROVENANCE: MIXED (OFFICIAL POLICY + SYNTHETIC TRADE FLOWS)"
            body = (
                "Tariff-policy and classification inputs are official. Trade flows come from "
                "the documented synthetic generator. **Estimates below measure whether the "
                "estimation code recovers a known ground truth. They are not evidence about "
                "the U.S. economy and must not be cited as empirical findings.**"
            )
        else:
            head = "DATA PROVENANCE: SYNTHETIC — PIPELINE VALIDATION ONLY"
            body = (
                "**Every number below was produced from simulated data with a known "
                "data-generating process. Nothing here is an empirical finding.**"
            )
        period = (
            f"{self.data_period_start} to {self.data_period_end}"
            if self.data_period_start
            else "n/a"
        )
        return (
            f"> **{head}**\n>\n"
            f"> {body}\n>\n"
            f"> run_id `{self.run_id}` · git `{self.git_commit}` · "
            f"config `{self.config_name}` (sha256 `{self.config_sha256[:12]}`) · "
            f"data period {period} · generated {self.created_utc}\n"
        )
