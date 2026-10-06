"""Pure tab-completion candidate generation for the interactive shell.

The readline wiring lives in :mod:`evm_wallet.cli`; this module only decides which
words could follow the tokens already typed, so it can be unit-tested directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .help import topic_names

COMMANDS = [
    "address",
    "balance",
    "block",
    "call",
    "chain",
    "checksum",
    "clear",
    "config",
    "contact",
    "estimate",
    "exit",
    "gas",
    "help",
    "history",
    "nonce",
    "quit",
    "send",
    "status",
    "token",
    "tx",
    "wallet",
]

SUBCOMMANDS: dict[str, list[str]] = {
    "wallet": [
        "default",
        "delete",
        "import",
        "info",
        "list",
        "new",
        "rename",
        "use",
        "verify",
        "watch",
    ],
    "chain": ["info", "list"],
    "token": ["add", "allowance", "balance", "info", "list", "remove", "revoke", "send"],
    "tx": ["inspect", "list", "watch"],
    "contact": ["add", "list", "remove"],
    "config": ["show"],
}

NETWORKS = ["local", "mainnet", "testnet"]
TRANSFER_FLAGS = ["--dry-run", "--yes"]
ALIAS_ARG_ACTIONS = {"default", "delete", "info", "use"}


def _match(candidates: Iterable[str], partial: str) -> list[str]:
    return sorted(candidate for candidate in set(candidates) if candidate.startswith(partial))


def complete_candidates(
    tokens: Sequence[str],
    partial: str,
    aliases: Iterable[str] = (),
) -> list[str]:
    """Return candidates for the whitespace-delimited token being completed.

    ``tokens`` are the complete tokens before the cursor; ``partial`` is the token
    currently being typed. ``aliases`` supplies the wallet aliases read from config.
    """
    words = list(tokens)
    alias_list = sorted(set(aliases))
    if not words:
        return _match(COMMANDS, partial)

    head = words[0]
    if head == "help":
        return _match(topic_names(), partial) if len(words) == 1 else []
    if head == "wallet":
        if len(words) == 1:
            return _match(SUBCOMMANDS["wallet"], partial)
        action = words[1]
        if len(words) == 2 and (action in ALIAS_ARG_ACTIONS or action == "rename"):
            return _match(alias_list, partial)
        return []
    if head == "chain":
        if len(words) == 1:
            return _match(SUBCOMMANDS["chain"], partial)
        if words[1] == "info" and len(words) == 2:
            return _match(NETWORKS, partial)
        return []
    if head == "token":
        if len(words) == 1:
            return _match(SUBCOMMANDS["token"], partial)
        if words[1] == "send" and partial.startswith("-"):
            return _match(TRANSFER_FLAGS, partial)
        return []
    if head == "tx":
        return _match(SUBCOMMANDS["tx"], partial) if len(words) == 1 else []
    if head in {"contact", "config"}:
        return _match(SUBCOMMANDS[head], partial) if len(words) == 1 else []
    if head == "send":
        return _match(TRANSFER_FLAGS, partial) if partial.startswith("-") else []
    if head in {"address", "balance", "nonce"} and len(words) == 1:
        return _match(alias_list, partial)
    return []
