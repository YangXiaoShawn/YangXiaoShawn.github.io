"""Dataset manifests.

Every dataset written to a data layer must be accompanied by a manifest so a
reader can tell what it is, when it was pulled, which vintage of the source it
reflects, and what is known to be wrong with it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import MANIFESTS
from .provenance import DataProvenance, sha256_file


@dataclass(slots=True)
class DatasetManifest:
    """Required metadata for any dataset persisted by this project."""

    dataset_id: str
    layer: str
    source: str
    source_url: str
    retrieval_timestamp_utc: str
    source_release_or_vintage: str
    date_range_start: str | None
    date_range_end: str | None
    schema_version: str
    product_code_vintage: str | None
    checksum_sha256: str
    row_count: int
    partition_keys: list[str]
    transformation_version: str
    data_provenance: str
    known_limitations: list[str] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_file(
        cls,
        path: Path,
        *,
        dataset_id: str,
        layer: str,
        source: str,
        source_url: str,
        source_release_or_vintage: str,
        schema_version: str,
        transformation_version: str,
        row_count: int,
        data_provenance: DataProvenance,
        product_code_vintage: str | None = None,
        date_range: tuple[str | None, str | None] = (None, None),
        partition_keys: list[str] | None = None,
        known_limitations: list[str] | None = None,
        columns: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DatasetManifest:
        return cls(
            dataset_id=dataset_id,
            layer=layer,
            source=source,
            source_url=source_url,
            retrieval_timestamp_utc=datetime.now(UTC).isoformat(),
            source_release_or_vintage=source_release_or_vintage,
            date_range_start=date_range[0],
            date_range_end=date_range[1],
            schema_version=schema_version,
            product_code_vintage=product_code_vintage,
            checksum_sha256=sha256_file(path),
            row_count=row_count,
            partition_keys=partition_keys or [],
            transformation_version=transformation_version,
            data_provenance=data_provenance.value,
            known_limitations=known_limitations or [],
            columns=columns or {},
            extra=extra or {},
        )

    def write(self, directory: Path | None = None) -> Path:
        directory = directory or MANIFESTS
        directory.mkdir(parents=True, exist_ok=True)
        out = directory / f"{self.dataset_id}.manifest.json"
        out.write_text(json.dumps(asdict(self), indent=2, sort_keys=False) + "\n")
        return out

    @staticmethod
    def load(dataset_id: str, directory: Path | None = None) -> DatasetManifest:
        directory = directory or MANIFESTS
        raw = json.loads((directory / f"{dataset_id}.manifest.json").read_text())
        return DatasetManifest(**raw)


def list_manifests(directory: Path | None = None) -> list[DatasetManifest]:
    directory = directory or MANIFESTS
    if not directory.exists():
        return []
    out = []
    for p in sorted(directory.glob("*.manifest.json")):
        try:
            out.append(DatasetManifest(**json.loads(p.read_text())))
        except (json.JSONDecodeError, TypeError):
            continue
    return out
