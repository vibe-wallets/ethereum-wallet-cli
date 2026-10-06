"""Monad-default entry point with its own configuration and wallet directory."""

from __future__ import annotations

from collections.abc import Sequence

from .cli import monad_main


def main(argv: Sequence[str] | None = None) -> int:
    return monad_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
