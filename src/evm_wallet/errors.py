"""Expected, user-facing error types raised by the CLI."""

from __future__ import annotations


class WalletCliError(Exception):
    """An expected, user-facing CLI error."""


class ConfigurationError(WalletCliError):
    """The local wallet configuration is invalid or unsafe to access."""


class FoundryError(WalletCliError):
    """A Foundry command failed."""
