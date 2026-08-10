"""Immutable-by-default Parquet artifacts with a local DuckDB catalog."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import duckdb
import polars as pl

from macro_nowcast.config import StorageConfig
from macro_nowcast.schema import (
    VintageObservation,
    observations_from_frame,
    observations_to_frame,
    validate_canonical_frame,
)


class StorageError(RuntimeError):
    """Base class for local artifact persistence failures."""


class ArtifactExistsError(StorageError):
    """Raised when an immutable artifact would be replaced implicitly."""


class DuplicateVintageError(StorageError):
    """Raised when a dataset contains duplicate canonical vintage keys."""


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VINTAGE_KEY = ["series_id", "observation_date", "realtime_start"]


def _identifier(value: str, name: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise StorageError(f"{name} must be a SQL-safe identifier")
    return value


def _sql_string(value: str) -> str:
    return value.replace("'", "''")


def _canonical_frame(
    rows: pl.DataFrame | Iterable[VintageObservation | Mapping[str, object]],
) -> pl.DataFrame:
    frame = (
        validate_canonical_frame(rows)
        if isinstance(rows, pl.DataFrame)
        else observations_to_frame(rows)
    )
    if frame.height and frame.select(pl.struct(_VINTAGE_KEY).is_duplicated().any()).item():
        raise DuplicateVintageError(
            "dataset contains duplicate (series_id, observation_date, realtime_start) rows"
        )
    return frame


class VintageStore:
    """Persist canonical observation datasets and expose them through DuckDB views."""

    def __init__(
        self,
        parquet_dir: str | Path,
        duckdb_path: str | Path | None = None,
    ) -> None:
        self.parquet_dir = Path(parquet_dir)
        self.duckdb_path = (
            Path(duckdb_path)
            if duckdb_path is not None
            else self.parquet_dir.parent / "macro_nowcast.duckdb"
        )

    @classmethod
    def from_config(cls, config: StorageConfig) -> VintageStore:
        return cls(config.parquet_dir, config.duckdb_path)

    def dataset_path(self, dataset_name: str = "vintage_observations") -> Path:
        dataset = _identifier(dataset_name, "dataset_name")
        return self.parquet_dir / f"{dataset}.parquet"

    def _connect(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        if not read_only:
            self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.duckdb_path), read_only=read_only)

    def register_view(
        self,
        parquet_path: str | Path,
        *,
        table_name: str = "vintage_observations",
    ) -> None:
        """Create or refresh a durable DuckDB view over one Parquet artifact."""

        table = _identifier(table_name, "table_name")
        path = Path(parquet_path).resolve()
        if not path.is_file():
            raise StorageError(f"Parquet artifact does not exist: {path.name}")
        escaped_path = _sql_string(str(path))
        with self._connect() as connection:
            connection.execute(
                f'CREATE OR REPLACE VIEW "{table}" AS '
                f"SELECT * FROM read_parquet('{escaped_path}')"
            )

    def write_observations(
        self,
        rows: pl.DataFrame | Iterable[VintageObservation | Mapping[str, object]],
        *,
        dataset_name: str = "vintage_observations",
        overwrite: bool = False,
        register: bool = True,
        table_name: str | None = None,
    ) -> Path:
        """Atomically write canonical rows; replacement requires explicit opt-in."""

        target = self.dataset_path(dataset_name)
        if target.exists() and not overwrite:
            raise ArtifactExistsError(
                f"artifact already exists and overwrite=False: {target.name}"
            )
        frame = _canonical_frame(rows)
        target.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=".parquet.tmp",
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            frame.write_parquet(
                temporary_path,
                compression="zstd",
                statistics=True,
            )
            os.replace(temporary_path, target)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        if register:
            self.register_view(target, table_name=table_name or dataset_name)
        return target

    write_parquet = write_observations
    write = write_observations

    def read_observations(
        self,
        dataset_name: str = "vintage_observations",
    ) -> pl.DataFrame:
        """Read and revalidate a named canonical Parquet artifact."""

        path = self.dataset_path(dataset_name)
        if not path.is_file():
            raise StorageError(f"Parquet artifact does not exist: {path.name}")
        return validate_canonical_frame(pl.read_parquet(path))

    read_parquet = read_observations
    read = read_observations

    def read_rows(
        self,
        dataset_name: str = "vintage_observations",
    ) -> list[VintageObservation]:
        return observations_from_frame(self.read_observations(dataset_name))

    def query(
        self,
        sql: str,
        parameters: Sequence[object] | None = None,
    ) -> pl.DataFrame:
        """Execute a local analytical query and materialize its result in Polars."""

        if not self.duckdb_path.is_file():
            raise StorageError("DuckDB catalog does not exist; register a dataset first")
        with self._connect(read_only=True) as connection:
            relation = connection.execute(sql, parameters or ())
            return relation.pl()

    def list_datasets(self) -> tuple[str, ...]:
        if not self.parquet_dir.is_dir():
            return ()
        return tuple(sorted(path.stem for path in self.parquet_dir.glob("*.parquet")))


def write_observations_parquet(
    rows: pl.DataFrame | Iterable[VintageObservation | Mapping[str, object]],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write one explicitly located Parquet file without creating a DuckDB catalog."""

    target = Path(path)
    store = VintageStore(target.parent)
    expected = store.dataset_path(target.stem)
    if expected != target:
        raise StorageError("Parquet path must have a simple SQL-safe filename")
    return store.write_observations(
        rows,
        dataset_name=target.stem,
        overwrite=overwrite,
        register=False,
    )


ParquetDuckDBStore = VintageStore
