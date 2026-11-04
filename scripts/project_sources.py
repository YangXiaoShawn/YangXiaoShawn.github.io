#!/usr/bin/env python3
"""Read build inputs from the unified open-economic-quant monorepo.

Prefers local monorepo checkout when present so builds run deterministically offline;
falls back to the monorepo on GitHub at the pinned commit if local checkout is unavailable.
The former standalone open-economic-quant-<project> repositories are archived.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MONOREPO_CANDIDATES = [
    ROOT.parent / "open-economic-quant",
    ROOT / "open-economic-quant",
]

FOLDER_BY_SLUG = {
    "casuallab": "CasualLab",
    "macroeconomics": "Macroeconomics",
    "realestate": "RealEstate",
    "tariff-incidence": "TariffIncidence",
    "microstructure": "Microstructure",
    "em-factor-timing": "EMFactorTiming",
    "polymarket-factors": "PolymarketFactors",
    "crypto-factors": "CryptoFactors",
}

MONOREPO = "YangXiaoShawn/open-economic-quant"
# Pinned monorepo commits for the GitHub fallback. TariffIncidence/reports/tariff_incidence_results.md
# at this commit is byte-identical to the former split-repo pin (729ebb8).
SOURCES = {
    "tariff-incidence": "65dc1d487f350d542d4a7a0ed59064d6a0f1ca72",
}


@lru_cache(maxsize=None)
def source_text(slug: str, relative: str) -> str:
    """Return one UTF-8 file from the monorepo checkout or pinned GitHub commit."""
    folder = FOLDER_BY_SLUG.get(slug)
    if folder:
        for base in MONOREPO_CANDIDATES:
            candidate = base / folder / relative
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
    commit = SOURCES[slug]
    url = f"https://raw.githubusercontent.com/{MONOREPO}/{commit}/{FOLDER_BY_SLUG[slug]}/{relative}"
    request = Request(url, headers={"User-Agent": "open-quant-econ-site-build"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")
