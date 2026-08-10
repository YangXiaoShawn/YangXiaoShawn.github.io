"""Fail early when setup is attempted with an unsupported interpreter."""

from __future__ import annotations

import sys


def main() -> None:
    if sys.version_info < (3, 12):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(f"Python 3.12+ is required; received {version}")
    print(f"Using Python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
