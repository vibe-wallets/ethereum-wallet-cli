from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import WalletCliError

CHAIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Chain:
    name: str
    chain_id: int
    rpc_url: str


BUILTIN_CHAINS: dict[str, Chain] = {
    "ethereum": Chain("ethereum", 1, "https://ethereum-rpc.publicnode.com"),
    "sepolia": Chain("sepolia", 11155111, "https://ethereum-sepolia-rpc.publicnode.com"),
    "monad": Chain("monad", 143, "https://rpc.monad.xyz"),
    "monad-testnet": Chain("monad-testnet", 10143, "https://testnet-rpc.monad.xyz"),
    "local": Chain("local", 31337, "http://127.0.0.1:8545"),
}

PROFILE_NETWORKS: dict[str, dict[str, str]] = {
    "ethereum": {"mainnet": "ethereum", "testnet": "sepolia", "local": "local"},
    "monad": {"mainnet": "monad", "testnet": "monad-testnet", "local": "local"},
}


def validate_chain_name(name: str) -> str:
    if not CHAIN_NAME_RE.fullmatch(name):
        raise WalletCliError(
            "Chain names must start with a lowercase letter and contain only lowercase "
            "letters, digits, '_' or '-' (up to 32 characters)."
        )
    return name


def validate_chain_id(value: int | str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise WalletCliError("Chain ID must be a positive decimal or 0x-prefixed integer.")
    try:
        chain_id = int(value, 0) if isinstance(value, str) else value
    except ValueError as exc:
        raise WalletCliError("Chain ID must be a positive decimal or 0x-prefixed integer.") from exc
    if chain_id <= 0:
        raise WalletCliError("Chain ID must be a positive integer.")
    return chain_id


def validate_rpc_url(value: str) -> str:
    if not isinstance(value, str):
        raise WalletCliError("RPC URL must be a string.")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise WalletCliError("RPC URL is malformed.") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise WalletCliError("RPC URL must be an absolute http:// or https:// URL.")
    if parts.username is not None or parts.password is not None:
        raise WalletCliError("RPC URLs cannot contain embedded usernames or passwords.")
    if parts.fragment:
        raise WalletCliError("RPC URLs cannot contain a fragment.")
    if port is not None and not 1 <= port <= 65535:
        raise WalletCliError("RPC URL port must be between 1 and 65535.")
    return value


def chain_from_config(name: str, value: object) -> Chain:
    if (
        not isinstance(name, str)
        or not isinstance(value, dict)
        or set(value) != {"chain_id", "rpc_url"}
    ):
        raise WalletCliError(f"Invalid configuration for chain '{name}'.")
    if isinstance(value.get("chain_id"), bool) or not isinstance(value.get("chain_id"), (int, str)):
        raise WalletCliError(f"Invalid configuration for chain '{name}'.")
    if not isinstance(value.get("rpc_url"), str):
        raise WalletCliError(f"Invalid configuration for chain '{name}'.")
    try:
        chain_id = validate_chain_id(value["chain_id"])
        rpc_url = validate_rpc_url(value["rpc_url"])
    except (KeyError, TypeError) as exc:
        raise WalletCliError(f"Invalid configuration for chain '{name}'.") from exc
    validate_chain_name(name)
    return Chain(name, chain_id, rpc_url)
