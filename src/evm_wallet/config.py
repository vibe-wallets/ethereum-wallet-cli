"""Secure, atomic wallet configuration and keystore metadata storage."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable

from .chains import BUILTIN_CHAINS, chain_from_config
from .errors import ConfigurationError, WalletCliError

ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KEYSTORE_FILE_RE = re.compile(r"^wallets/[0-9a-f]{32}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SYMBOL_MAX_LENGTH = 32


def default_config_dir() -> Path:
    override = os.environ.get("ETHEREUM_WALLET_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "ethereum-wallet-cli"
    return Path.home() / ".config" / "ethereum-wallet-cli"


def new_config() -> dict[str, Any]:
    return {
        "version": 2,
        "default_chain": "ethereum",
        "current_chain": "ethereum",
        "default_wallet": None,
        "current_wallet": None,
        "chains": {
            name: {"chain_id": chain.chain_id, "rpc_url": chain.rpc_url}
            for name, chain in BUILTIN_CHAINS.items()
        },
        "wallets": {},
        "contacts": {},
        "tokens": {},
    }


def validate_alias(alias: str) -> str:
    if not ALIAS_RE.fullmatch(alias):
        raise WalletCliError(
            "Wallet aliases must start with a letter or digit and contain only letters, "
            "digits, '.', '_' or '-' (up to 64 characters)."
        )
    return alias


def validate_contact_name(name: str) -> str:
    if not ALIAS_RE.fullmatch(name):
        raise WalletCliError(
            "Contact names must start with a letter or digit and contain only letters, "
            "digits, '.', '_' or '-' (up to 64 characters)."
        )
    return name


def validate_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    text = symbol.strip()
    if not text or len(text) > SYMBOL_MAX_LENGTH or any(character < " " for character in text):
        raise WalletCliError(
            f"Token symbols must be 1 to {SYMBOL_MAX_LENGTH} printable characters."
        )
    return text


def _migrate_document(document: object) -> object:
    """Upgrade old documents without changing the version 2 schema.

    Version 1 documents gain empty contacts and tokens. Then any built-in chain added
    by a newer build (for example BNB Smart Chain) is backfilled, so a config created
    before that chain existed can still select it. The schema shape is unchanged, so
    the version stays at 2.
    """
    if (
        isinstance(document, dict)
        and type(document.get("version")) is int
        and document.get("version") == 1
    ):
        migrated = dict(document)
        migrated["version"] = 2
        migrated.setdefault("contacts", {})
        migrated.setdefault("tokens", {})
        document = migrated
    if isinstance(document, dict) and isinstance(document.get("chains"), dict):
        chains = document["chains"]
        missing = {
            name: {"chain_id": chain.chain_id, "rpc_url": chain.rpc_url}
            for name, chain in BUILTIN_CHAINS.items()
            if name not in chains
        }
        if missing:
            document = {**document, "chains": {**chains, **missing}}
    return document


class ConfigStore:
    """Secure, atomic config and alias metadata storage."""

    def __init__(self, config_dir: str | os.PathLike[str] | None = None):
        self.directory = Path(config_dir).expanduser() if config_dir else default_config_dir()
        self.directory = Path(os.path.abspath(self.directory))
        self.config_path = self.directory / "config.json"
        self.wallet_dir = self.directory / "wallets"
        self.lock_path = self.directory / ".config.lock"

    def ensure_directory(self, *, wallets: bool = False) -> None:
        """Create the config tree with private permissions, rejecting symlinks."""
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._ensure_real_directory(self.directory)
            os.chmod(self.directory, 0o700)
            if wallets:
                self.wallet_dir.mkdir(mode=0o700, exist_ok=True)
                self._ensure_real_directory(self.wallet_dir)
                os.chmod(self.wallet_dir, 0o700)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot access wallet configuration directory: {exc.strerror}."
            ) from exc

    @staticmethod
    def _ensure_real_directory(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise ConfigurationError(f"Cannot inspect protected directory '{path.name}'.") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ConfigurationError(
                f"Protected path '{path.name}' must be a real directory, not a symlink."
            )

    def load(self) -> dict[str, Any]:
        """Read and validate config.json, returning defaults when it is absent."""
        self._reject_symlink(self.directory, "configuration directory")
        if self.directory.exists():
            self._ensure_real_directory(self.directory)
        if not self.config_path.exists() and not self.config_path.is_symlink():
            return new_config()
        self._reject_symlink(self.config_path, "configuration file")
        try:
            fd = os.open(self.config_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ConfigurationError("Configuration path is not a regular file.")
                os.chmod(self.config_path, 0o600)
                with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
                    data = json.load(handle)
            finally:
                os.close(fd)
        except ConfigurationError:
            raise
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise ConfigurationError(
                "Cannot read config.json; the file is malformed or inaccessible."
            ) from exc
        return self._validate_document(_migrate_document(data))

    def update(self, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Apply a change under an exclusive lock and write config.json atomically."""
        self.ensure_directory()
        lock_fd: int | None = None
        try:
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            lock_fd = os.open(self.lock_path, flags, 0o600)
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise ConfigurationError("Configuration lock path is not a regular file.")
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            state = self.load()
            change(state)
            state = self._validate_document(state)
            self._write_atomic(state)
            return state
        except ConfigurationError:
            raise
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot update wallet configuration: {exc.strerror}."
            ) from exc
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    def allocate_keystore_name(self) -> str:
        """Return a fresh random 32-character hex keystore file name."""
        return secrets.token_hex(16)

    def keystore_path(self, wallet: dict[str, Any]) -> Path:
        """Validate and return the keystore path recorded for a wallet alias."""
        relative = wallet.get("keystore")
        if not isinstance(relative, str) or not KEYSTORE_FILE_RE.fullmatch(relative):
            raise ConfigurationError("Wallet keystore path in config.json is invalid.")
        self._reject_symlink(self.directory, "configuration directory")
        self._ensure_real_directory(self.directory)
        self._reject_symlink(self.wallet_dir, "wallet directory")
        self._ensure_real_directory(self.wallet_dir)
        path = self.directory / relative
        self._reject_symlink(path, "wallet keystore")
        try:
            info = path.lstat()
        except OSError as exc:
            raise ConfigurationError(
                "Encrypted wallet keystore is missing or inaccessible."
            ) from exc
        if not stat.S_ISREG(info.st_mode):
            raise ConfigurationError("Encrypted wallet keystore must be a regular file.")
        os.chmod(path, 0o600)
        return path

    def _write_atomic(self, state: dict[str, Any]) -> None:
        self._reject_symlink(self.config_path, "configuration file")
        fd, temporary_name = tempfile.mkstemp(prefix=".config-", dir=self.directory)
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.config_path)
            os.chmod(self.config_path, 0o600)
            dir_fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _reject_symlink(path: Path, label: str) -> None:
        try:
            if stat.S_ISLNK(path.lstat().st_mode):
                raise ConfigurationError(f"The {label} cannot be a symlink.")
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ConfigurationError(f"Cannot inspect the {label}.") from exc

    @staticmethod
    def _validate_document(document: object) -> dict[str, Any]:
        if (
            not isinstance(document, dict)
            or type(document.get("version")) is not int
            or document.get("version") != 2
        ):
            raise ConfigurationError("config.json must be an object with version 2.")
        expected = {
            "version",
            "default_chain",
            "current_chain",
            "default_wallet",
            "current_wallet",
            "chains",
            "wallets",
            "contacts",
            "tokens",
        }
        if set(document) != expected:
            raise ConfigurationError("config.json contains missing or unknown top-level fields.")
        chains = document["chains"]
        wallets = document["wallets"]
        contacts = document["contacts"]
        tokens = document["tokens"]
        if not all(isinstance(section, dict) for section in (chains, wallets, contacts, tokens)):
            raise ConfigurationError(
                "config.json chains, wallets, contacts, and tokens must be objects."
            )
        ConfigStore._validate_chains(chains)
        ConfigStore._validate_wallets(wallets)
        ConfigStore._validate_contacts(contacts)
        ConfigStore._validate_tokens(tokens, chains)
        for key in ("default_chain", "current_chain"):
            name = document[key]
            if not isinstance(name, str) or name not in chains:
                raise ConfigurationError(f"config.json {key} refers to an unknown chain.")
        for key in ("default_wallet", "current_wallet"):
            alias = document[key]
            if alias is not None and (not isinstance(alias, str) or alias not in wallets):
                raise ConfigurationError(f"config.json {key} refers to an unknown wallet.")
        return document

    @staticmethod
    def _validate_chains(chains: dict[str, Any]) -> None:
        for name, chain_data in chains.items():
            try:
                chain_from_config(name, chain_data)
            except WalletCliError as exc:
                raise ConfigurationError(str(exc)) from exc

    @staticmethod
    def _validate_wallets(wallets: dict[str, Any]) -> None:
        for alias, metadata in wallets.items():
            if (
                not isinstance(alias, str)
                or not ALIAS_RE.fullmatch(alias)
                or not isinstance(metadata, dict)
            ):
                raise ConfigurationError("config.json contains an invalid wallet alias entry.")
            # A watch-only wallet records just an address; a signing wallet also
            # records its encrypted keystore path.
            if set(metadata) not in ({"address"}, {"keystore", "address"}):
                raise ConfigurationError(
                    f"Wallet '{alias}' metadata must contain address, with keystore for a signing wallet."
                )
            if "keystore" in metadata:
                keystore = metadata["keystore"]
                if not isinstance(keystore, str) or not KEYSTORE_FILE_RE.fullmatch(keystore):
                    raise ConfigurationError(f"Wallet '{alias}' has an invalid keystore path.")
            address = metadata["address"]
            if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
                raise ConfigurationError(f"Wallet '{alias}' has an invalid address.")

    @staticmethod
    def _validate_contacts(contacts: dict[str, Any]) -> None:
        for name, address in contacts.items():
            if not isinstance(name, str) or not ALIAS_RE.fullmatch(name):
                raise ConfigurationError("config.json contains an invalid contact name.")
            if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
                raise ConfigurationError(f"Contact '{name}' has an invalid address.")

    @staticmethod
    def _validate_tokens(tokens: dict[str, Any], chains: dict[str, Any]) -> None:
        for chain_name, entries in tokens.items():
            if not isinstance(chain_name, str) or chain_name not in chains:
                raise ConfigurationError("config.json saved tokens refer to an unknown chain.")
            if not isinstance(entries, dict):
                raise ConfigurationError("config.json saved tokens must map a chain to addresses.")
            for address, symbol in entries.items():
                if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
                    raise ConfigurationError("config.json contains an invalid saved token address.")
                if symbol is not None and (
                    not isinstance(symbol, str)
                    or not symbol.strip()
                    or len(symbol) > SYMBOL_MAX_LENGTH
                ):
                    raise ConfigurationError("config.json contains an invalid saved token symbol.")
