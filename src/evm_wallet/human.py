"""Terminal styling and aligned human-readable output.

This is the Python port of the sibling Solana wallet CLI's output layer. It keeps
human output pleasant on an interactive terminal while remaining plain when the
destination is redirected or the environment opts out. JSON output never uses
these helpers, so machine-readable stdout stays unchanged.

Color is only used when the destination is a TTY, ``NO_COLOR`` is unset, and
``TERM`` is not ``dumb``. Meaningful text never depends on color.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Sequence, TextIO

Tone = str

ANSI: dict[Tone, str] = {
    "heading": "\x1b[1;36m",
    "emphasis": "\x1b[1m",
    "muted": "\x1b[2m",
    "success": "\x1b[1;32m",
    "info": "\x1b[36m",
    "warning": "\x1b[1;33m",
    "error": "\x1b[1;31m",
}
RESET = "\x1b[0m"
CLEAR_SCREEN = "\x1b[2J\x1b[H"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _is_tty(stream: TextIO | None) -> bool:
    if stream is None:
        stream = sys.stdout
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def color_enabled(stream: TextIO | None = None) -> bool:
    """Return whether ANSI color should be used for ``stream``."""
    if not _is_tty(stream):
        return False
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return True


def color(
    value: str,
    tone: Tone,
    *,
    enabled: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Wrap ``value`` in one ANSI style when color is enabled."""
    if enabled is None:
        enabled = color_enabled(stream)
    if not enabled or not value:
        return value
    return f"{ANSI[tone]}{value}{RESET}"


def display_width(value: str) -> int:
    """Strip ANSI controls and count terminal cells, including wide glyphs."""
    plain = ANSI_RE.sub("", value)
    width = 0
    for character in plain:
        if unicodedata.combining(character) or character == "\u200d":
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def shorten_address(value: str, *, leading: int = 6, trailing: int = 4) -> str:
    """Shorten a hex address for labels where the full value is nearby."""
    if len(value) <= leading + trailing + 1:
        return value
    return f"{value[:leading]}…{value[-trailing:]}"


def section_title(value: str, *, enabled: bool | None = None, stream: TextIO | None = None) -> str:
    """Render a visually distinct section title."""
    return color(value, "heading", enabled=enabled, stream=stream)


def network_label(name: str, *, enabled: bool | None = None, stream: TextIO | None = None) -> str:
    """Label real-fund networks clearly while keeping a text fallback."""
    if name == "mainnet":
        return color("MAINNET · REAL FUNDS", "warning", enabled=enabled, stream=stream)
    return color(name.upper(), "info", enabled=enabled, stream=stream)


def key_value_rows(
    rows: Sequence[Sequence[object]],
    *,
    enabled: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render aligned label/value pairs that stay readable without color."""
    if not rows:
        return ""
    labels = [str(row[0]) for row in rows]
    label_width = max(display_width(label) for label in labels)
    lines = []
    for label, row in zip(labels, rows):
        value = str(row[1])
        tone = str(row[2]) if len(row) > 2 and row[2] is not None else None
        styled_label = color(label, "muted", enabled=enabled, stream=stream)
        styled_value = color(value, tone, enabled=enabled, stream=stream) if tone else value
        padding = " " * (label_width - display_width(label))
        lines.append(f"{styled_label}{padding}: {styled_value}")
    return "\n".join(lines)


def terminal_width(stream: TextIO | None = None) -> int:
    """Return the printable width for ``stream`` or a sensible fallback."""
    columns = 0
    if stream is not None:
        fileno = getattr(stream, "fileno", None)
        if callable(fileno):
            try:
                columns = os.get_terminal_size(fileno()).columns
            except (OSError, ValueError):
                columns = 0
    configured = os.environ.get("COLUMNS", "")
    if columns <= 0 and configured.isdigit() and int(configured) > 0:
        columns = int(configured)
    return columns if columns > 0 else 100


def table(
    rows: Sequence[Sequence[object]],
    headers: Sequence[str] | None = None,
    *,
    width: int | None = None,
    enabled: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render an aligned table, or labeled rows when it does not fit.

    The compact form preserves full addresses rather than clipping values a
    user may need to copy into a follow-up command.
    """
    data = [[str(cell) for cell in row] for row in rows]
    if not data and not headers:
        return ""
    header_row = [str(header) for header in headers] if headers else None
    all_rows = ([header_row] if header_row else []) + data
    columns = max(len(row) for row in all_rows)
    widths = [
        max(display_width(row[index]) if index < len(row) else 0 for row in all_rows)
        for index in range(columns)
    ]
    available = width if width is not None else terminal_width(stream)
    required = sum(widths) + max(0, columns - 1) * 2
    if header_row and required > available:
        blocks = []
        for row in data:
            blocks.append(
                "\n".join(
                    f"{color(header, 'muted', enabled=enabled, stream=stream)}: "
                    f"{row[index] if index < len(row) else ''}"
                    for index, header in enumerate(header_row)
                )
            )
        return "\n\n".join(blocks)

    def format_row(row: Sequence[str]) -> str:
        cells = [
            (row[index] if index < len(row) else "")
            + " " * (widths[index] - display_width(row[index] if index < len(row) else ""))
            for index in range(columns)
        ]
        return "  ".join(cells).rstrip()

    lines = []
    if header_row:
        lines.append(color(format_row(header_row), "emphasis", enabled=enabled, stream=stream))
        lines.append(
            color(
                "  ".join("-" * width for width in widths),
                "muted",
                enabled=enabled,
                stream=stream,
            )
        )
    lines.extend(format_row(row) for row in data)
    return "\n".join(lines)


def action_preview(
    title: str,
    rows: Sequence[Sequence[object]],
    *,
    enabled: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render a transaction preview before user confirmation."""
    return (
        f"{section_title(title, enabled=enabled, stream=stream)}\n"
        f"{key_value_rows(rows, enabled=enabled, stream=stream)}"
    )


def format_transaction_receipt(
    *,
    action: str,
    network: str,
    rows: Sequence[Sequence[object]] = (),
    signature: str | None = None,
    explorer: str | None = None,
    enabled: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render a consistent, copyable receipt after a submitted transaction."""
    parts = [
        color(f"{action} submitted", "success", enabled=enabled, stream=stream),
        key_value_rows(
            [("Network", network_label(network, enabled=enabled, stream=stream)), *rows],
            enabled=enabled,
            stream=stream,
        ),
    ]
    tail: list[Sequence[object]] = []
    if signature:
        tail.append(("Transaction", signature))
    if explorer:
        tail.append(("Explorer", explorer))
    if tail:
        parts.append(key_value_rows(tail, enabled=enabled, stream=stream))
    return "\n".join(parts)


def style_help(text: str, *, enabled: bool | None = None, stream: TextIO | None = None) -> str:
    """Add visual hierarchy to help output while leaving the content unchanged."""
    lines = text.split("\n")
    styled = []
    for line in lines:
        stripped = line.strip()
        is_heading = (
            bool(stripped)
            and stripped == line
            and (stripped.endswith(":") or ANSI_RE.sub("", stripped).isupper())
        )
        styled.append(section_title(line, enabled=enabled, stream=stream) if is_heading else line)
    return "\n".join(styled)
