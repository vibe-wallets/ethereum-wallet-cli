"""Persistent interactive command history kept in the profile config directory.

Only command text is stored; the CLI never accepts keys or passphrases as command
arguments, so the history file never contains secrets. Directory permissions are
managed by :class:`evm_wallet.config.ConfigStore`.
"""

from __future__ import annotations

import os
from pathlib import Path

HISTORY_LIMIT = 1000


def read_history(path: Path, limit: int = HISTORY_LIMIT) -> list[str]:
    """Return the most recent history entries, newest last."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    entries = [line for line in text.splitlines() if line.strip()]
    return entries[-limit:]


def append_history(path: Path, line: str, limit: int = HISTORY_LIMIT) -> None:
    """Append one command to the capped history file.

    History is a convenience, so a write failure never fails the command that was
    just run.
    """
    if not line.strip():
        return
    entries = read_history(path, limit=limit)
    entries.append(line)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(entries[-limit:]) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass
