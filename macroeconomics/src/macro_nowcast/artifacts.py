"""Reproducibility metadata and deterministic artifact helpers."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import polars as pl


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def frame_hash(frame: pl.DataFrame) -> str:
    """Hash a deterministically ordered frame as Arrow IPC bytes."""

    buffer = BytesIO()
    frame.write_ipc(buffer, compression="uncompressed")
    return sha256_bytes(buffer.getvalue())


def config_hash(path: Path) -> str:
    return sha256_file(path)


def package_versions(names: list[str] | None = None) -> dict[str, str]:
    selected = names or [
        "macro-nowcast",
        "polars",
        "duckdb",
        "pyarrow",
        "numpy",
        "scikit-learn",
        "statsmodels",
    ]
    versions: dict[str, str] = {}
    for name in selected:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime, Path)):
        return value.isoformat() if not isinstance(value, Path) else str(value)
    if hasattr(value, "item"):
        return str(value.item())  # type: ignore[union-attr]
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n"
    )
    return path
