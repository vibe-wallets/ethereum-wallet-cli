"""Append-only local log of transactions this CLI broadcast.

EVM RPC endpoints cannot enumerate a wallet's history, so the CLI records the
hashes it sends itself. The log stores only public transaction metadata and never
keys or passphrases. It is compacted when it grows past a size threshold.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TXLOG_LIMIT = 500
COMPACT_BYTES = 64 * 1024


def read_transactions(path: Path, limit: int = 50) -> list[dict[str, object]]:
    """Return up to ``limit`` parsed records, newest last; skip damaged lines."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    records: list[dict[str, object]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records[-limit:]


def append_transaction(path: Path, record: dict[str, object], limit: int = TXLOG_LIMIT) -> None:
    """Append one record; failures are ignored so logging never fails a send."""
    line = json.dumps(record, sort_keys=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        os.chmod(path, 0o600)
    except OSError:
        return
    _compact(path, limit)


def _compact(path: Path, limit: int) -> None:
    try:
        if path.stat().st_size < COMPACT_BYTES:
            return
        records = read_transactions(path, limit)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass
