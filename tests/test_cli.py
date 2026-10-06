"""One-shot JSON, argument parsing and shell behavior tests."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from evm_wallet.cli import main, monad_main
from evm_wallet.config import ConfigStore

ROOT = Path(__file__).resolve().parents[1]


class TTYStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ethereum-wallet-cli-test-")
        self.addCleanup(self.temporary.cleanup)
        self.config_dir = Path(self.temporary.name) / "config"

    def test_one_shot_json_success_has_a_single_machine_readable_envelope(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--config-dir", str(self.config_dir), "-c", "chain list", "--json"])

        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertEqual(
            stderr.getvalue().splitlines(), ["[wrapper] No external command ran (local command)."]
        )
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "chain list")
        self.assertEqual({chain["chain_id"] for chain in payload["chains"]}, {1, 11155111, 31337})

    def test_one_shot_json_error_is_json_on_stderr_with_nonzero_status(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "evm_wallet",
                "--config-dir",
                str(self.config_dir),
                "-c",
                "made-up command",
                "--json",
            ],
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertEqual(len(process.stderr.splitlines()), 2)
        payload = json.loads(process.stderr.splitlines()[0])
        self.assertFalse(payload["ok"])
        self.assertIn("Unknown command", payload["error"])
        self.assertIn("No external command ran", process.stderr.splitlines()[1])

    def test_direct_words_and_command_string_are_both_supported(self) -> None:
        first = io.StringIO()
        with redirect_stdout(first), redirect_stderr(io.StringIO()):
            exit_code = main(
                ["--config-dir", str(self.config_dir), "--network", "testnet", "chain", "info"]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("testnet: chain 11155111", first.getvalue())

        second = io.StringIO()
        with redirect_stdout(second), redirect_stderr(io.StringIO()):
            exit_code = main(
                ["--config-dir", str(self.config_dir), "--network", "testnet", "-c", "chain info"]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("testnet: chain 11155111", second.getvalue())

    def test_interactive_shell_splits_quoted_command_and_handles_bad_input(self) -> None:
        shell_input = TTYStringIO("made-up command\nchain info\nexit\n")
        shell_output = TTYStringIO()
        shell_error = io.StringIO()

        from unittest.mock import patch

        with (
            patch("sys.stdin", shell_input),
            patch("sys.stdout", shell_output),
            redirect_stderr(shell_error),
        ):
            exit_code = main(["--config-dir", str(self.config_dir)])

        self.assertEqual(exit_code, 0)
        self.assertIn("mainnet: chain 1", shell_output.getvalue())
        self.assertIn("ethereum[mainnet](no-wallet)>", shell_output.getvalue())
        self.assertIn("Unknown command", shell_error.getvalue())

    def test_json_mode_without_a_one_shot_command_is_rejected(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["--config-dir", str(self.config_dir), "--json"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--json applies", stderr.getvalue())

    def test_entrypoints_use_separate_xdg_stores_and_ignore_stale_saved_chain(self) -> None:
        xdg = Path(self.temporary.name) / "xdg"
        evm_dir = xdg / "ethereum-wallet-cli"
        monad_dir = xdg / "monad-wallet-cli"
        evm_store = ConfigStore(evm_dir)
        monad_store = ConfigStore(monad_dir)
        evm_store.update(
            lambda state: state.update({"default_chain": "monad", "current_chain": "monad"})
        )
        monad_store.update(
            lambda state: state.update({"default_chain": "ethereum", "current_chain": "ethereum"})
        )
        evm_before = evm_store.config_path.read_bytes()
        monad_before = monad_store.config_path.read_bytes()

        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=True):
            evm_output = io.StringIO()
            with redirect_stdout(evm_output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["-c", "chain info"]), 0)
            monad_output = io.StringIO()
            with redirect_stdout(monad_output), redirect_stderr(io.StringIO()):
                self.assertEqual(monad_main(["-c", "chain info"]), 0)

        self.assertIn("mainnet: chain 1", evm_output.getvalue())
        self.assertIn("mainnet: chain 143", monad_output.getvalue())
        self.assertNotEqual(evm_dir, monad_dir)
        self.assertEqual(evm_store.config_path.read_bytes(), evm_before)
        self.assertEqual(monad_store.config_path.read_bytes(), monad_before)

    def test_each_entrypoint_reads_only_its_own_chain_and_rpc_environment(self) -> None:
        xdg = Path(self.temporary.name) / "xdg-env"
        environment = {
            "XDG_CONFIG_HOME": str(xdg),
            "ETHEREUM_WALLET_NETWORK": "testnet",
            "ETHEREUM_WALLET_RPC_URL": "https://ethereum-env.example.invalid/rpc",
            "MONAD_WALLET_NETWORK": "testnet",
            "MONAD_WALLET_RPC_URL": "https://monad-env.example.invalid/rpc",
        }
        evm_output = io.StringIO()
        monad_output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True):
            with redirect_stdout(evm_output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["-c", "chain info"]), 0)
            with redirect_stdout(monad_output), redirect_stderr(io.StringIO()):
                self.assertEqual(monad_main(["-c", "chain info"]), 0)

        self.assertIn(
            "testnet: chain 11155111 · https://ethereum-env.example.invalid/rpc",
            evm_output.getvalue(),
        )
        self.assertIn(
            "testnet: chain 10143 · https://monad-env.example.invalid/rpc", monad_output.getvalue()
        )

    def test_cli_flags_override_entrypoint_environment_without_saving_selection(self) -> None:
        config = self.config_dir
        store = ConfigStore(config)
        store.update(
            lambda state: state.update({"default_chain": "monad", "current_chain": "monad"})
        )
        before = store.config_path.read_bytes()
        output = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {
                    "ETHEREUM_WALLET_NETWORK": "testnet",
                    "ETHEREUM_WALLET_RPC_URL": "https://env.example.invalid",
                },
                clear=True,
            ),
            redirect_stdout(output),
            redirect_stderr(io.StringIO()),
        ):
            exit_code = main(
                [
                    "--config-dir",
                    str(config),
                    "--network",
                    "mainnet",
                    "--rpc-url",
                    "http://127.0.0.1:8545",
                    "-c",
                    "chain info",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("mainnet: chain 1 · http://127.0.0.1:8545", output.getvalue())
        self.assertEqual(store.config_path.read_bytes(), before)

    def test_same_wallet_alias_is_independent_in_each_entrypoint_store(self) -> None:
        xdg = Path(self.temporary.name) / "alias-xdg"
        evm_store = ConfigStore(xdg / "ethereum-wallet-cli")
        monad_store = ConfigStore(xdg / "monad-wallet-cli")

        def seed(store: ConfigStore, address: str) -> None:
            store.ensure_directory(wallets=True)
            filename = "a" * 32
            store.wallet_dir.joinpath(filename).write_text(
                json.dumps({"address": address[2:], "crypto": {"cipher": "fixture"}}),
                encoding="utf-8",
            )

            def add(state: dict) -> None:
                state["wallets"]["primary"] = {
                    "keystore": f"wallets/{filename}",
                    "address": address,
                }
                state["default_wallet"] = "primary"

            store.update(add)

        evm_address = "0x" + "11" * 20
        monad_address = "0x" + "22" * 20
        seed(evm_store, evm_address)
        seed(monad_store, monad_address)
        evm_output = io.StringIO()
        monad_output = io.StringIO()
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=True):
            with redirect_stdout(evm_output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["-c", "wallet list"]), 0)
            with redirect_stdout(monad_output), redirect_stderr(io.StringIO()):
                self.assertEqual(monad_main(["-c", "wallet list"]), 0)

        self.assertIn(f"primary: {evm_address}", evm_output.getvalue())
        self.assertNotIn(monad_address, evm_output.getvalue())
        self.assertIn(f"primary: {monad_address}", monad_output.getvalue())
        self.assertNotIn(evm_address, monad_output.getvalue())

    def test_network_selector_cannot_cross_the_entrypoint_profile(self) -> None:
        for entrypoint, network in ((main, "monad"), (monad_main, "ethereum")):
            with self.subTest(network=network):
                stderr = io.StringIO()
                with (
                    patch.dict(
                        os.environ,
                        {"XDG_CONFIG_HOME": str(Path(self.temporary.name) / network)},
                        clear=True,
                    ),
                    redirect_stderr(stderr),
                ):
                    exit_code = entrypoint(["--network", network, "-c", "chain info"])
                self.assertEqual(exit_code, 2)
                self.assertIn("invalid choice", stderr.getvalue())

    def test_chain_commands_are_read_only_and_profile_filtered(self) -> None:
        xdg = Path(self.temporary.name) / "profile-filter-xdg"
        evm_store = ConfigStore(xdg / "ethereum-wallet-cli")
        monad_store = ConfigStore(xdg / "monad-wallet-cli")
        evm_store.update(
            lambda state: state.update({"default_chain": "monad", "current_chain": "monad"})
        )
        monad_store.update(
            lambda state: state.update({"default_chain": "ethereum", "current_chain": "ethereum"})
        )
        evm_before = evm_store.config_path.read_bytes()
        monad_before = monad_store.config_path.read_bytes()

        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=True):
            evm_output = io.StringIO()
            monad_output = io.StringIO()
            with redirect_stdout(evm_output), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["-c", "chain list", "--json"]), 0)
            with redirect_stdout(monad_output), redirect_stderr(io.StringIO()):
                self.assertEqual(monad_main(["-c", "chain list", "--json"]), 0)

        evm_chains = json.loads(evm_output.getvalue())["chains"]
        monad_chains = json.loads(monad_output.getvalue())["chains"]
        self.assertTrue(evm_chains)
        self.assertTrue(monad_chains)
        self.assertEqual({chain["chain_id"] for chain in evm_chains}, {1, 11155111, 31337})
        self.assertEqual({chain["chain_id"] for chain in monad_chains}, {143, 10143, 31337})
        self.assertEqual(evm_store.config_path.read_bytes(), evm_before)
        self.assertEqual(monad_store.config_path.read_bytes(), monad_before)

    def test_removed_chain_mutation_commands_fail_without_changing_config(self) -> None:
        store = ConfigStore(self.config_dir)
        store.update(lambda state: None)
        before = store.config_path.read_bytes()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                ["--config-dir", str(self.config_dir), "-c", "chain use monad", "--json"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Usage: chain list", json.loads(stderr.getvalue().splitlines()[0])["error"])
        self.assertEqual(store.config_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
