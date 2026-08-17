"""Shared adapter machinery: caching HTTP, credential gating, fixture fallback.

Every adapter follows the same contract:

* ``available()``   -- can this adapter reach its source right now?
* ``fetch_*()``     -- retrieve bytes into ``data/raw`` and record a checksum.
* ``parse_*()``     -- turn raw bytes into a staged table. Pure, testable, offline.

Splitting fetch from parse is what makes the project testable without network
access or credentials: parsers run against committed fixtures in CI, and the
fetchers are exercised separately under the ``network`` pytest marker.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..paths import RAW
from ..provenance import sha256_bytes

USER_AGENT = (
    "tariff-incidence-research/0.1 (academic replication project; "
    "contact: repository maintainer)"
)


class SourceUnavailable(RuntimeError):
    """Raised when an official source cannot be reached or is not authorised."""


class CredentialRequired(SourceUnavailable):
    """Raised when a source needs an API key that is not configured."""

    def __init__(self, source: str, env_var: str, signup_url: str) -> None:
        super().__init__(
            f"{source} requires an API key. Set the {env_var} environment variable. "
            f"Free registration: {signup_url}"
        )
        self.source = source
        self.env_var = env_var
        self.signup_url = signup_url


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    path: Path
    sha256: str
    n_bytes: int
    from_cache: bool


def cached_get(
    url: str,
    cache_name: str,
    *,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    subdir: str = "http",
    timeout: float = 180.0,
    max_retries: int = 3,
    force: bool = False,
) -> FetchResult:
    """GET ``url`` into ``data/raw/<subdir>/<cache_name>``, reusing any cached copy.

    Caching is not an optimisation here, it is a reproducibility requirement:
    the raw bytes that produced a result stay on disk with their checksum, so a
    later source revision cannot silently change a published number.
    """
    dest = RAW / subdir / cache_name
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        data = dest.read_bytes()
        return FetchResult(url, dest, sha256_bytes(data), len(data), True)

    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                resp = client.get(url, params=list(params.items()) if isinstance(params, Mapping) else (list(params) if params else None))
                resp.raise_for_status()
                data = resp.content
        except (httpx.HTTPError, OSError) as exc:  # noqa: PERF203
            last = exc
            time.sleep(1.5 * (attempt + 1))
            continue

        if not data:
            last = SourceUnavailable(f"empty response from {url}")
            time.sleep(1.5 * (attempt + 1))
            continue

        dest.write_bytes(data)
        return FetchResult(str(resp.url), dest, sha256_bytes(data), len(data), False)

    raise SourceUnavailable(f"could not retrieve {url}: {last}")


def require_env(source: str, env_var: str, signup_url: str) -> str:
    val = os.environ.get(env_var, "").strip()
    if not val:
        raise CredentialRequired(source, env_var, signup_url)
    return val


def has_env(env_var: str) -> bool:
    return bool(os.environ.get(env_var, "").strip())
