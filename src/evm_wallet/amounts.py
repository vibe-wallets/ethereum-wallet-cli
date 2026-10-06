from __future__ import annotations

import re

from .errors import WalletCliError

AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
UINT256_MAX = (1 << 256) - 1


def validate_address(value: str, label: str = "address") -> str:
    if not ADDRESS_RE.fullmatch(value):
        raise WalletCliError(f"{label.capitalize()} must be a 20-byte 0x-prefixed hex address.")
    return value


def validate_tx_hash(value: str) -> str:
    if not TX_HASH_RE.fullmatch(value):
        raise WalletCliError("Transaction hash must be a 32-byte 0x-prefixed hex value.")
    return value


def to_base_units(amount: str, decimals: int) -> int:
    if not isinstance(amount, str) or not AMOUNT_RE.fullmatch(amount):
        raise WalletCliError(
            "Amount must be a non-negative decimal string without exponent notation."
        )
    if decimals < 0 or decimals > 255:
        raise WalletCliError("Token decimals are outside the supported range.")
    whole, dot, fraction = amount.partition(".")
    if len(fraction) > decimals:
        raise WalletCliError(f"Amount has more than {decimals} fractional decimal places.")
    raw = int(whole) * (10**decimals)
    if dot:
        raw += int(fraction.ljust(decimals, "0") or "0")
    if raw <= 0:
        raise WalletCliError("Amount must be greater than zero.")
    if raw > UINT256_MAX:
        raise WalletCliError("Amount exceeds the maximum uint256 value.")
    return raw


def format_units(raw_amount: int | str, decimals: int) -> str:
    value = int(raw_amount)
    if value < 0 or decimals < 0:
        raise ValueError("raw amount and decimals must be non-negative")
    if decimals == 0:
        return str(value)
    base = 10**decimals
    whole, fraction = divmod(value, base)
    if fraction == 0:
        return str(whole)
    return f"{whole}.{fraction:0{decimals}d}".rstrip("0")
