#!/usr/bin/env python3
"""Read build inputs from the standalone project repositories at pinned commits.

The website no longer carries copies of the project packages. Files that the
build still needs are fetched from GitHub at the commit recorded here, so a
build is reproducible and a change upstream never alters the site silently.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.request import Request, urlopen

SOURCES = {
    "tariff-incidence": (
        "YangXiaoShawn/open-economic-quant-tariff-incidence",
        "729ebb821bf5b982b5a7d2ec2bd6086a8d7c2df2",
    ),
}


@lru_cache(maxsize=None)
def source_text(slug: str, relative: str) -> str:
    """Return one UTF-8 file from a project repository at its pinned commit."""
    repo, commit = SOURCES[slug]
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{relative}"
    request = Request(url, headers={"User-Agent": "open-quant-econ-site-build"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")
