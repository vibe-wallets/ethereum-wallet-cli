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
        "version": 1,
        "default_chain": "ethereum",
        "current_chain": "ethereum",
        "default_wallet": None,
        "current_wallet": None,
        "chains": {
            name: {"chain_id": chain.chain_id, "rpc_url": chain.rpc_url}
            for name, chain in BUILTIN_CHAINS.items()
        },
        "wallets": {},
    }


def validate_alias(alias: str) -> str:
    if not ALIAS_RE.fullmatch(alias):
        raise WalletCliError(
            "Wallet aliases must start with a letter or digit and contain only letters, "
            "digits, '.', '_' or '-' (up to 64 characters)."
        )
    return alias


class ConfigStore:
    """Secure, atomic config and alias metadata storage."""

    def __init__(self, config_dir: str | os.PathLike[str] | None = None):
        self.directory = Path(config_dir).expanduser() if config_dir else default_config_dir()
        self.directory = Path(os.path.abspath(self.directory))
        self.config_path = self.directory / "config.json"
        self.wallet_dir = self.directory / "wallets"
        self.lock_path = self.directory / ".config.lock"

    def ensure_directory(self, *, wallets: bool = False) -> None:
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
        return self._validate_document(data)

    def update(self, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
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
        return secrets.token_hex(16)

    def keystore_path(self, wallet: dict[str, Any]) -> Path:
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
            or document.get("version") != 1
        ):
            raise ConfigurationError("config.json must be an object with version 1.")
        expected = {
            "version",
            "default_chain",
            "current_chain",
            "default_wallet",
            "current_wallet",
            "chains",
            "wallets",
        }
        if set(document) != expected:
            raise ConfigurationError("config.json contains missing or unknown top-level fields.")
        if not isinstance(document["chains"], dict) or not isinstance(document["wallets"], dict):
            raise ConfigurationError("config.json chains and wallets must be objects.")
        for name, chain_data in document["chains"].items():
            try:
                chain_from_config(name, chain_data)
            except WalletCliError as exc:
                raise ConfigurationError(str(exc)) from exc
        for key in ("default_chain", "current_chain"):
            name = document[key]
            if not isinstance(name, str) or name not in document["chains"]:
                raise ConfigurationError(f"config.json {key} refers to an unknown chain.")
        for alias, metadata in document["wallets"].items():
            if (
                not isinstance(alias, str)
                or not ALIAS_RE.fullmatch(alias)
                or not isinstance(metadata, dict)
            ):
                raise ConfigurationError("config.json contains an invalid wallet alias entry.")
            if set(metadata) != {"keystore", "address"}:
                raise ConfigurationError(
                    f"Wallet '{alias}' metadata must contain keystore and address only."
                )
            if not isinstance(metadata["keystore"], str) or not KEYSTORE_FILE_RE.fullmatch(
                metadata["keystore"]
            ):
                raise ConfigurationError(f"Wallet '{alias}' has an invalid keystore path.")
            if not isinstance(metadata["address"], str) or not ADDRESS_RE.fullmatch(
                metadata["address"]
            ):
                raise ConfigurationError(f"Wallet '{alias}' has an invalid address.")
        for key in ("default_wallet", "current_wallet"):
            alias = document[key]
            if alias is not None and (
                not isinstance(alias, str) or alias not in document["wallets"]
            ):
                raise ConfigurationError(f"config.json {key} refers to an unknown wallet.")
        return document
