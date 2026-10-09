"""Unit coverage for exact value conversion and protected config storage."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evm_wallet.amounts import format_units, to_base_units
from evm_wallet.config import ConfigStore, new_config
from evm_wallet.errors import ConfigurationError, WalletCliError


class AmountTests(unittest.TestCase):
    def test_exact_decimal_conversion_never_uses_float_rounding(self) -> None:
        self.assertEqual(to_base_units("0.000000000000000001", 18), 1)
        self.assertEqual(to_base_units("1.000000000000000001", 18), 1_000_000_000_000_000_001)
        self.assertEqual(to_base_units("123.4500", 4), 1_234_500)
        self.assertEqual(format_units(1_000_000_000_000_000_001, 18), "1.000000000000000001")
        self.assertEqual(format_units("100000", 4), "10")

    def test_amount_validation_rejects_ambiguous_or_unrepresentable_values(self) -> None:
        for value in ("0", "0.0", "-1", "+1", "01", ".5", "1.", "1e-18", "NaN", " 1"):
            with self.subTest(value=value), self.assertRaises(WalletCliError):
                to_base_units(value, 18)
        with self.assertRaises(WalletCliError):
            to_base_units("1.0000001", 6)
        with self.assertRaises(WalletCliError):
            to_base_units(str(1 << 256), 0)
        with self.assertRaises(WalletCliError):
            to_base_units("1", 256)


class ConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="evm-wallet-config-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "wallet config"
        self.store = ConfigStore(self.directory)

    def write_state(self, change=None) -> dict:
        def update(state: dict) -> None:
            if change:
                change(state)

        return self.store.update(update)

    def test_config_and_wallet_directories_have_private_permissions(self) -> None:
        self.store.ensure_directory(wallets=True)
        self.write_state()

        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.wallet_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.config_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.lock_path.stat().st_mode & 0o777, 0o600)

    def test_config_load_repairs_permissions_and_preserves_chain_wallet_aliases(self) -> None:
        wallet_name = self.store.allocate_keystore_name()

        def add_wallet(state: dict) -> None:
            state["wallets"]["cold-wallet_1"] = {
                "keystore": f"wallets/{wallet_name}",
                "address": "0x" + "ab" * 20,
            }
            state["default_wallet"] = "cold-wallet_1"
            state["current_wallet"] = "cold-wallet_1"
            state["chains"]["my-rollup"] = {
                "chain_id": 1234,
                "rpc_url": "https://rpc.example.test",
            }

        written = self.write_state(add_wallet)
        self.store.config_path.chmod(0o644)
        loaded = self.store.load()

        self.assertEqual(loaded, written)
        self.assertEqual(self.store.config_path.stat().st_mode & 0o777, 0o600)

    def test_version_one_config_is_migrated_with_empty_contacts_and_tokens(self) -> None:
        self.store.ensure_directory()
        legacy = new_config()
        legacy["version"] = 1
        del legacy["contacts"]
        del legacy["tokens"]
        self.store.config_path.write_text(json.dumps(legacy), encoding="utf-8")

        loaded = self.store.load()
        self.assertEqual(loaded["version"], 2)
        self.assertEqual(loaded["contacts"], {})
        self.assertEqual(loaded["tokens"], {})

    def test_missing_builtin_chains_are_backfilled_without_a_version_bump(self) -> None:
        self.store.ensure_directory()
        legacy = new_config()
        del legacy["chains"]["bsc"]
        del legacy["chains"]["bsc-testnet"]
        self.store.config_path.write_text(json.dumps(legacy), encoding="utf-8")

        loaded = self.store.load()
        self.assertEqual(loaded["version"], 2)
        self.assertEqual(loaded["chains"]["bsc"]["chain_id"], 56)
        self.assertEqual(loaded["chains"]["bsc-testnet"]["chain_id"], 97)
        self.assertEqual(loaded["chains"]["bsc"]["rpc_url"], "https://bsc-rpc.publicnode.com")

    def test_malformed_and_unknown_schema_files_fail_closed(self) -> None:
        self.store.ensure_directory()
        self.store.config_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            self.store.load()

        self.store.config_path.write_text(json.dumps({"version": 1}), encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            self.store.load()

        boolean_version = new_config()
        boolean_version["version"] = True
        self.store.config_path.write_text(json.dumps(boolean_version), encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            self.store.load()

    def test_alias_and_keystore_paths_cannot_escape_wallet_directory(self) -> None:
        for alias, relative in (
            ("../escape", "wallets/" + "a" * 32),
            ("ok", "../../secret"),
            ("ok", "/tmp/key"),
        ):
            with self.subTest(alias=alias, relative=relative):
                self.store.ensure_directory()
                invalid_state = new_config()
                invalid_state["wallets"][alias] = {
                    "keystore": relative,
                    "address": "0x" + "11" * 20,
                }
                self.store.config_path.write_text(json.dumps(invalid_state), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    self.store.load()

    def test_keystore_must_be_regular_and_is_restricted_to_mode_0600(self) -> None:
        self.store.ensure_directory(wallets=True)
        wallet_name = self.store.allocate_keystore_name()
        wallet = {"keystore": f"wallets/{wallet_name}", "address": "0x" + "cd" * 20}
        path = self.directory / wallet["keystore"]
        path.write_text("encrypted-test-fixture", encoding="utf-8")
        path.chmod(0o644)

        self.assertEqual(self.store.keystore_path(wallet), path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        path.unlink()
        path.symlink_to(self.directory / "outside")
        with self.assertRaises(ConfigurationError):
            self.store.keystore_path(wallet)

    def test_config_and_wallet_directory_symlinks_are_rejected(self) -> None:
        real = Path(self.temporary.name) / "real"
        real.mkdir()
        link = Path(self.temporary.name) / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ConfigurationError):
            ConfigStore(link).ensure_directory()

    def test_config_file_symlink_is_rejected(self) -> None:
        self.store.ensure_directory()
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        self.store.config_path.symlink_to(outside)

        with self.assertRaises(ConfigurationError):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
