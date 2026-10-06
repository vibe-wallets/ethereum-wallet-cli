"""Command-level tests with Cast replaced at its subprocess boundary."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from evm_wallet.app import Application, execute
from evm_wallet.cli import _run_one
from evm_wallet.errors import ConfigurationError, FoundryError, WalletCliError

ADDRESS = "0x" + "11" * 20
DESTINATION = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
TX_HASH = "0x" + "aa" * 32


class TTY:
    def isatty(self) -> bool:
        return True


class FakeCastRunner:
    def __init__(self, *, chain_id: int = 1):
        self.chain_id = chain_id
        self.calls: list[tuple[list[str], dict]] = []
        self.eth_balance = 0x1BC16D674EC80001
        self.token_decimals = 18
        self.token_balance = 1_234_567_890_123_456_789
        self.nonce = 3
        self.gas_price = "1500000000\n"
        self.base_fee = "1000000000\n"
        self.allowance = 2_500_000
        self.name = "Test Token"
        self.symbol = "TT"
        self.block_number = 16
        self.transfer_success = True
        self.send_status = "0x1"
        self.send_hash: str | None = TX_HASH
        self.send_empty = False
        self.receipt_response = "null"
        self.receipt_sequence: list[str] = []
        self.estimate = "51234\n"

    def __call__(self, command: list[str], **kwargs):
        self.calls.append((command, kwargs))
        args = command[1:]
        if args[:1] == ["chain-id"]:
            output = str(self.chain_id)
        elif args[:1] == ["rpc"] and len(args) > 1 and args[1] == "eth_getBalance":
            output = hex(self.eth_balance)
        elif args[:1] == ["rpc"] and len(args) > 1 and args[1] == "eth_getTransactionCount":
            output = hex(self.nonce)
        elif args[:1] == ["gas-price"]:
            output = self.gas_price
        elif args[:1] == ["base-fee"]:
            output = self.base_fee
        elif args[:1] == ["to-check-sum-address"]:
            output = args[1]
        elif args[:1] == ["block"]:
            output = json.dumps(
                {
                    "number": hex(self.block_number),
                    "hash": "0x" + "ab" * 32,
                    "timestamp": "0x64",
                    "gasLimit": "0x5208",
                    "gasUsed": "0x5208",
                    "baseFeePerGas": "0x3b9aca00",
                    "transactions": ["0x1", "0x2"],
                }
            )
        elif args[:1] == ["rpc"] and len(args) > 1 and args[1] == "eth_getTransactionReceipt":
            output = (
                self.receipt_sequence.pop(0) if self.receipt_sequence else self.receipt_response
            )
        elif args[:1] == ["call"]:
            signature = args[2]
            if signature == "transfer(address,uint256)":
                output = "0x" + "0" * 63 + ("1" if self.transfer_success else "0")
            elif signature == "approve(address,uint256)":
                output = "0x" + "0" * 63 + ("1" if self.transfer_success else "0")
            elif signature == "name()(string)":
                output = self.name
            elif signature == "symbol()(string)":
                output = self.symbol
            elif signature == "totalSupply()(uint256)":
                output = json.dumps([str(self.token_balance)])
            elif signature == "allowance(address,address)(uint256)":
                output = json.dumps([str(self.allowance)])
            else:
                raw = (
                    self.token_decimals if signature == "decimals()(uint8)" else self.token_balance
                )
                output = json.dumps([raw if signature == "decimals()(uint8)" else str(raw)])
        elif args[:1] == ["estimate"]:
            output = self.estimate
        elif args[:1] == ["send"]:
            data = {}
            if self.send_hash is not None:
                data["transactionHash"] = self.send_hash
            if self.send_status is not None:
                data["status"] = self.send_status
            output = json.dumps(
                {
                    "schema_version": 1,
                    "success": True,
                    "data": data,
                    "errors": [],
                    "warnings": [],
                }
            )
            if self.send_empty:
                output = ""
        elif args[:1] == ["tx"]:
            output = json.dumps(
                {
                    "schema_version": 1,
                    "success": True,
                    "data": {"hash": TX_HASH, "to": DESTINATION},
                }
            )
        elif args[:2] == ["wallet", "new"]:
            directory, name = Path(args[2]), args[3]
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            (directory / name).write_text(
                json.dumps({"crypto": {"cipher": "test-only"}, "id": "test", "version": 3}),
                encoding="utf-8",
            )
            output = f"Created encrypted keystore.\nAddress: {ADDRESS}\n"
        elif args[:2] == ["wallet", "import"]:
            name = args[2]
            directory = Path(args[args.index("--keystore-dir") + 1])
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            (directory / name).write_text(
                json.dumps({"crypto": {"cipher": "test-only"}, "id": "test", "version": 3}),
                encoding="utf-8",
            )
            output = f"Keystore saved successfully. Address: {DESTINATION}\n"
        else:
            raise AssertionError(f"Unexpected Foundry command: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def commands(self) -> list[list[str]]:
        return [call[0][1:] for call in self.calls]


class AppCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="evm-wallet-app-")
        self.addCleanup(self.temporary.cleanup)
        self.config_dir = Path(self.temporary.name) / "config"
        self.runner = FakeCastRunner()
        self.prompts: list[str] = []
        self.app = self.make_app()

    def make_app(self, *, terminal: bool = False, answer: str = "yes") -> Application:
        def prompt(text: str) -> str:
            self.prompts.append(text)
            return answer

        tty = TTY() if terminal else None
        return Application(
            self.config_dir,
            cast_executable="mock-cast",
            runner=self.runner,
            input_fn=prompt,
            stdin=tty,
            stdout=tty,
        )

    def add_wallet(self, alias: str = "primary", address: str = ADDRESS) -> Path:
        self.app.store.ensure_directory(wallets=True)
        keystore_name = self.app.store.allocate_keystore_name()
        keystore = self.app.store.wallet_dir / keystore_name
        keystore.write_text(
            json.dumps({"address": address[2:], "crypto": {"cipher": "test-only"}}),
            encoding="utf-8",
        )

        def add(state: dict) -> None:
            state["wallets"][alias] = {"keystore": f"wallets/{keystore_name}", "address": address}
            if state["default_wallet"] is None:
                state["default_wallet"] = alias

        self.app.store.update(add)
        return keystore

    def test_wallet_aliases_are_supported_and_chain_selection_is_read_only(self) -> None:
        self.add_wallet()
        result = execute(["wallet", "list"], self.app)
        self.assertEqual(result["wallets"][0]["alias"], "primary")
        self.assertTrue(result["wallets"][0]["current"])
        before = self.app.store.load()
        chain_info = execute(["chain", "info"], self.app)
        self.assertEqual(chain_info["name"], "mainnet")
        self.assertEqual(chain_info["chain_id"], 1)
        after = self.app.store.load()
        self.assertEqual(after["default_chain"], before["default_chain"])
        self.assertEqual(after["current_chain"], before["current_chain"])

    def test_chain_mutation_commands_are_removed(self) -> None:
        before = self.app.store.load()
        for command in (
            ["chain", "use", "monad"],
            ["chain", "add", "my-rollup", "31337", "http://127.0.0.1:8545"],
            ["chain", "default", "monad"],
        ):
            with self.subTest(command=command), self.assertRaises(WalletCliError):
                execute(command, self.app)
        after = self.app.store.load()
        self.assertEqual(after["default_chain"], before["default_chain"])
        self.assertEqual(after["current_chain"], before["current_chain"])

    def test_wallet_use_is_session_only_and_wallet_default_is_saved(self) -> None:
        self.add_wallet("primary", ADDRESS)
        self.add_wallet("secondary", DESTINATION)
        self.app.store.update(lambda state: state.update({"current_wallet": "secondary"}))
        self.app = self.make_app()

        self.assertEqual(self.app.active_wallet_alias(), "primary")
        before = self.app.store.load()
        execute(["wallet", "use", "secondary"], self.app)
        self.assertEqual(self.app.active_wallet_alias(), "secondary")
        after_use = self.app.store.load()
        self.assertEqual(after_use["default_wallet"], before["default_wallet"])
        self.assertEqual(after_use["current_wallet"], before["current_wallet"])

        execute(["wallet", "default", "secondary"], self.app)
        persisted = self.app.store.load()
        self.assertEqual(persisted["default_wallet"], "secondary")
        self.assertEqual(self.app.active_wallet_alias(), "secondary")
        next_invocation = Application(
            self.config_dir, cast_executable="mock-cast", runner=self.runner
        )
        self.assertEqual(next_invocation.active_wallet_alias(), "secondary")

    def test_wallet_new_and_import_use_foundry_encrypted_keystore_prompts(self) -> None:
        self.app = self.make_app(terminal=True)
        created = execute(["wallet", "new", "generated"], self.app)
        imported = execute(["wallet", "import", "imported"], self.app)

        self.assertEqual(created["alias"], "generated")
        self.assertEqual(imported["alias"], "imported")
        state = self.app.store.load()
        self.assertEqual(state["default_wallet"], "generated")
        self.assertEqual(self.app.active_wallet_alias(), "imported")
        self.assertEqual(self.app.store.wallet_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(list(self.app.store.wallet_dir.iterdir())), 2)
        for path in self.app.store.wallet_dir.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        commands = self.runner.commands()
        new_command = next(command for command in commands if command[:2] == ["wallet", "new"])
        import_command = next(
            command for command in commands if command[:2] == ["wallet", "import"]
        )
        self.assertEqual(new_command[2], str(self.app.store.wallet_dir))
        self.assertIn("--interactive", import_command)
        self.assertNotIn("--private-key", import_command)
        self.assertNotIn("--unsafe-password", import_command)

    def test_invalid_chain_url_with_embedded_credentials_is_rejected(self) -> None:
        from evm_wallet.chains import validate_rpc_url

        with self.assertRaises(WalletCliError):
            validate_rpc_url("https://user:pass@example.test/rpc")

    def test_native_balance_decodes_rpc_hex_and_formats_exact_wei(self) -> None:
        result = execute(["balance", ADDRESS], self.app)
        self.assertEqual(result["balance_base_units"], str(self.runner.eth_balance))
        self.assertEqual(result["balance_native"], "2.000000000000000001")
        self.assertEqual(
            self.runner.commands(),
            [
                ["chain-id", "--rpc-url", "https://ethereum-rpc.publicnode.com"],
                [
                    "rpc",
                    "eth_getBalance",
                    ADDRESS,
                    "latest",
                    "--rpc-url",
                    "https://ethereum-rpc.publicnode.com",
                ],
            ],
        )

    def test_native_send_uses_exact_integer_amount_and_cast_json_result(self) -> None:
        keystore = self.add_wallet()
        self.app = self.make_app(terminal=True)

        result = execute(["send", DESTINATION, "1.000000000000000001", "--yes"], self.app)
        self.assertEqual(result["amount_base_units"], "1000000000000000001")
        self.assertEqual(result["transaction_hash"], TX_HASH)
        send = self.runner.commands()[-1]
        self.assertEqual(
            send,
            [
                "send",
                DESTINATION,
                "--from",
                ADDRESS,
                "--value",
                "1000000000000000001wei",
                "--keystore",
                str(keystore),
                "--chain",
                "1",
                "--rpc-url",
                "https://ethereum-rpc.publicnode.com",
                "--json",
            ],
        )
        self.assertEqual(
            [command[0] for command in self.runner.commands()],
            ["chain-id", "estimate", "chain-id", "send"],
        )
        self.assertEqual(self.prompts, [])

    def test_preflight_estimate_includes_exact_amount_before_confirmation(self) -> None:
        self.add_wallet()
        self.app = self.make_app(terminal=True, answer="no")

        with self.assertRaisesRegex(WalletCliError, "cancelled"):
            execute(["send", DESTINATION, "1.000000000000000001"], self.app)

        commands = self.runner.commands()
        estimate = next(command for command in commands if command[0] == "estimate")
        self.assertIn("1000000000000000001wei", estimate)
        self.assertNotIn("send", [command[0] for command in commands])
        self.assertEqual(len(self.prompts), 1)

    def test_send_requires_tty_even_with_yes_and_decline_never_broadcasts(self) -> None:
        self.add_wallet()
        with self.assertRaisesRegex(WalletCliError, "interactive terminal"):
            execute(["send", DESTINATION, "1", "--yes"], self.app)
        commands = [command[0] for command in self.runner.commands()]
        self.assertNotIn("send", commands)

        self.app = self.make_app(terminal=True, answer="no")
        with self.assertRaisesRegex(WalletCliError, "cancelled"):
            execute(["send", DESTINATION, "1"], self.app)
        self.assertEqual(len(self.prompts), 1)
        self.assertNotIn("send", [command[0] for command in self.runner.commands()])

    def test_send_chain_mismatch_never_calls_cast_send(self) -> None:
        self.add_wallet()
        self.app = self.make_app(terminal=True)
        self.runner.chain_id = 10_000

        with self.assertRaisesRegex(FoundryError, "refusing to continue"):
            execute(["send", DESTINATION, "0.1", "--yes"], self.app)

        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.commands()[0][0], "chain-id")

    def test_native_dry_run_estimates_without_terminal_or_broadcast(self) -> None:
        self.add_wallet()
        result = execute(["send", DESTINATION, "0.1", "--dry-run"], self.app)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["amount_base_units"], "100000000000000000")
        self.assertEqual(result["estimated_gas"], "51234")
        self.assertEqual(self.runner.commands()[-1][0], "estimate")
        self.assertNotIn("send", [command[0] for command in self.runner.commands()])

    def test_erc20_balance_handles_realistic_large_uint_output(self) -> None:
        self.add_wallet()
        result = execute(["token", "balance", TOKEN, ADDRESS], self.app)

        self.assertEqual(result["decimals"], 18)
        self.assertEqual(result["balance_raw"], "1234567890123456789")
        self.assertEqual(result["balance"], "1.234567890123456789")
        calls = self.runner.commands()
        self.assertEqual(calls[1][2], "decimals()(uint8)")
        self.assertEqual(calls[3][2], "balanceOf(address)(uint256)")

    def test_erc20_send_converts_amount_using_contract_decimals(self) -> None:
        keystore = self.add_wallet()
        self.runner.token_decimals = 6
        self.app = self.make_app(terminal=True)

        result = execute(["token", "send", TOKEN, DESTINATION, "2.500001", "--yes"], self.app)
        self.assertEqual(result["amount_raw"], "2500001")
        send = self.runner.commands()[-1]
        self.assertEqual(
            send[0:5], ["send", TOKEN, "transfer(address,uint256)", DESTINATION, "2500001"]
        )
        self.assertIn(str(keystore), send)
        self.assertEqual(self.prompts, [])

    def test_erc20_false_transfer_simulation_stops_before_estimate_and_broadcast(self) -> None:
        self.add_wallet()
        self.runner.transfer_success = False
        self.app = self.make_app(terminal=True)

        with self.assertRaisesRegex(WalletCliError, "returned false"):
            execute(["token", "send", TOKEN, DESTINATION, "1", "--yes"], self.app)

        commands = [command[0] for command in self.runner.commands()]
        self.assertIn("call", commands)
        self.assertNotIn("estimate", commands)
        self.assertNotIn("send", commands)

    def test_amount_precision_is_checked_before_any_network_call(self) -> None:
        self.add_wallet()
        self.runner.token_decimals = 6

        with self.assertRaises(WalletCliError):
            execute(["token", "send", TOKEN, DESTINATION, "1.0000001", "--dry-run"], self.app)
        commands = [command[0] for command in self.runner.commands()]
        self.assertEqual(commands, ["chain-id", "call"])
        self.assertNotIn("send", commands)
        self.assertNotIn("estimate", commands)

    def test_keystore_address_mismatch_fails_before_using_wallet(self) -> None:
        path = self.add_wallet()
        path.write_text(json.dumps({"address": "44" * 20, "crypto": {}}), encoding="utf-8")

        with self.assertRaises(ConfigurationError):
            execute(["address"], self.app)
        self.assertEqual(self.runner.calls, [])

    def test_json_flag_is_accepted_by_execute_without_affecting_result(self) -> None:
        result = execute(["chain", "list", "--json"], self.app)
        self.assertEqual(result["command"], "chain list")
        self.assertEqual({chain["chain_id"] for chain in result["chains"]}, {1, 11155111, 31337})

    def test_status_reports_network_wallet_and_native_balance(self) -> None:
        self.add_wallet()
        result = execute(["status"], self.app)
        self.assertEqual(result["command"], "status")
        self.assertEqual(result["profile"], "ethereum")
        self.assertEqual(result["network"], "mainnet")
        self.assertEqual(result["chain_id"], 1)
        self.assertEqual(result["wallet"], "primary")
        self.assertEqual(result["address"], ADDRESS)
        self.assertEqual(result["balance_native"], "2.000000000000000001")
        self.assertEqual([command[0] for command in self.runner.commands()], ["chain-id", "rpc"])

    def test_status_without_a_wallet_checks_the_network_only(self) -> None:
        result = execute(["status"], self.app)
        self.assertNotIn("wallet", result)
        self.assertNotIn("balance_native", result)
        self.assertEqual([command[0] for command in self.runner.commands()], ["chain-id"])

    def test_gas_and_nonce_read_from_the_network(self) -> None:
        self.add_wallet()
        gas = execute(["gas"], self.app)
        self.assertEqual(gas["gas_price_wei"], "1500000000")
        self.assertEqual(gas["gas_price_gwei"], "1.5")

        nonce = execute(["nonce"], self.app)
        self.assertEqual(nonce["nonce"], "3")
        self.assertEqual(nonce["address"], ADDRESS)
        explicit = execute(["nonce", DESTINATION], self.app)
        self.assertEqual(explicit["address"], DESTINATION)

    def test_wallet_rename_moves_alias_and_updates_defaults(self) -> None:
        self.add_wallet("primary")
        self.add_wallet("secondary", DESTINATION)
        renamed = execute(["wallet", "rename", "primary", "daily"], self.app)
        self.assertEqual(renamed["old_alias"], "primary")
        self.assertEqual(renamed["alias"], "daily")
        state = self.app.store.load()
        self.assertEqual(set(state["wallets"]), {"daily", "secondary"})
        self.assertEqual(state["default_wallet"], "daily")
        self.assertEqual(self.app.active_wallet_alias(), "daily")
        with self.assertRaisesRegex(WalletCliError, "already exists"):
            execute(["wallet", "rename", "daily", "secondary"], self.app)
        with self.assertRaisesRegex(WalletCliError, "must differ"):
            execute(["wallet", "rename", "daily", "daily"], self.app)

    def test_wallet_delete_removes_the_local_keystore_after_confirmation(self) -> None:
        keystore = self.add_wallet("primary")
        declining = self.make_app(answer="no")
        with self.assertRaisesRegex(WalletCliError, "cancelled"):
            execute(["wallet", "delete", "primary"], declining)
        self.assertTrue(keystore.exists())

        deleted = execute(["wallet", "delete", "primary", "--yes"], self.app)
        self.assertEqual(deleted["alias"], "primary")
        self.assertFalse(keystore.exists())
        state = self.app.store.load()
        self.assertNotIn("primary", state["wallets"])
        self.assertIsNone(state["default_wallet"])

    def test_history_lists_and_limits_recorded_commands(self) -> None:
        self.app.history = ["wallet list", "status", "balance"]
        result = execute(["history"], self.app)
        self.assertEqual(result["entries"], ["wallet list", "status", "balance"])
        limited = execute(["history", "2"], self.app)
        self.assertEqual(limited["entries"], ["status", "balance"])
        with self.assertRaisesRegex(WalletCliError, "Usage: history"):
            execute(["history", "zero"], self.app)

    def test_help_topics_and_index(self) -> None:
        index = execute(["help"], self.app)
        self.assertIn("COMMANDS", index["text"])
        topic = execute(["help", "wallet"], self.app)
        self.assertEqual(topic["topic"], "wallet")
        self.assertIn("wallet rename", topic["text"])
        unknown = execute(["help", "nope"], self.app)
        self.assertIn("No detailed help", unknown["text"])
        with self.assertRaisesRegex(WalletCliError, "Usage: help"):
            execute(["help", "wallet", "extra"], self.app)

    def test_transaction_inspect_handles_pending_rpc_receipt(self) -> None:
        result = execute(["tx", "inspect", TX_HASH], self.app)
        self.assertTrue(result["pending"])
        self.assertIsNone(result["receipt"])
        commands = [command for command in self.runner.commands()]
        self.assertTrue(any("eth_getTransactionReceipt" in command for command in commands))

    def test_transaction_inspect_includes_mined_receipt(self) -> None:
        self.runner.receipt_response = json.dumps({"transactionHash": TX_HASH, "status": "0x1"})
        result = execute(["tx", "inspect", TX_HASH], self.app)

        self.assertFalse(result["pending"])
        self.assertEqual(result["receipt"]["status"], "0x1")

    def test_mined_failed_send_reports_transaction_hash(self) -> None:
        self.add_wallet()
        self.runner.send_status = "0x0"
        self.app = self.make_app(terminal=True)

        with self.assertRaisesRegex(WalletCliError, TX_HASH):
            execute(["send", DESTINATION, "0.1", "--yes"], self.app)

    def test_send_rejects_receipt_missing_a_valid_status(self) -> None:
        self.add_wallet()
        self.runner.send_status = None
        self.app = self.make_app(terminal=True)

        with self.assertRaisesRegex(FoundryError, TX_HASH) as caught:
            execute(["send", DESTINATION, "0.1", "--yes"], self.app)
        self.assertIn("may have been broadcast", str(caught.exception))

    def test_send_rejects_receipt_missing_transaction_hash(self) -> None:
        self.add_wallet()
        self.runner.send_hash = None
        self.app = self.make_app(terminal=True)

        with self.assertRaisesRegex(FoundryError, "valid native transaction receipt") as caught:
            execute(["send", DESTINATION, "0.1", "--yes"], self.app)
        self.assertIn("may have been broadcast", str(caught.exception))

    def test_send_rejects_empty_cast_receipt_output(self) -> None:
        self.add_wallet()
        self.runner.send_empty = True
        self.app = self.make_app(terminal=True)

        with self.assertRaisesRegex(FoundryError, "valid native transaction receipt") as caught:
            execute(["send", DESTINATION, "0.1", "--yes"], self.app)
        self.assertIn("may have been broadcast", str(caught.exception))

    def test_cli_trace_lists_ordered_foundry_commands_and_redacts_rpc_url(self) -> None:
        self.add_wallet()
        private_rpc = "https://rpc.example.invalid/private-token"
        self.app.store.update(
            lambda state: state["chains"].update(
                {"private-l2": {"chain_id": 1, "rpc_url": private_rpc}}
            )
        )
        self.app.startup_chain = "private-l2"
        self.app = self.make_app(terminal=True)
        self.app.startup_chain = "private-l2"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_one(["send", DESTINATION, "0.1", "--yes"], self.app, json_output=True)

        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        traces = [line for line in stderr.getvalue().splitlines() if line.startswith("[wrapper]")]
        self.assertEqual(len(traces), 4)
        self.assertIn("cast chain-id", traces[0])
        self.assertIn("cast estimate", traces[1])
        self.assertIn("cast chain-id", traces[2])
        self.assertIn("cast send", traces[3])
        self.assertTrue(all("<redacted-rpc-url>" in line for line in traces))
        self.assertNotIn(private_rpc, stderr.getvalue())

    def test_cli_error_prints_checked_command_trace_without_broadcast(self) -> None:
        self.add_wallet()
        private_rpc = "https://rpc.example.invalid/error-token"
        self.app.store.update(
            lambda state: state["chains"].update(
                {"private-l2": {"chain_id": 1, "rpc_url": private_rpc}}
            )
        )
        self.app = self.make_app(terminal=True)
        self.app.startup_chain = "private-l2"
        self.runner.chain_id = 31337
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = _run_one(["send", DESTINATION, "0.1", "--yes"], self.app, json_output=True)

        lines = stderr.getvalue().splitlines()
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("refusing to continue", json.loads(lines[0])["error"])
        self.assertEqual(len([line for line in lines if line.startswith("[wrapper]")]), 1)
        self.assertIn("cast chain-id", lines[1])
        self.assertNotIn("cast estimate", stderr.getvalue())
        self.assertNotIn("cast send", stderr.getvalue())
        self.assertNotIn(private_rpc, stderr.getvalue())

    def test_config_show_reports_resolved_settings_without_rpc(self) -> None:
        self.add_wallet()
        result = execute(["config", "show"], self.app)
        self.assertEqual(result["command"], "config show")
        self.assertEqual(result["profile"], "ethereum")
        self.assertEqual(result["network"], "mainnet")
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["wallet"], "primary")
        self.assertEqual(result["contact_count"], 0)
        self.assertEqual(self.runner.calls, [])

    def test_checksum_block_and_call_outputs(self) -> None:
        checksum = execute(["checksum", ADDRESS], self.app)
        self.assertEqual(checksum["checksum"], ADDRESS)
        self.assertEqual(
            [command[0] for command in self.runner.commands()], ["to-check-sum-address"]
        )

        block = execute(["block", "latest"], self.app)
        self.assertEqual(block["number"], "16")
        self.assertEqual(block["transaction_count"], 2)
        self.assertEqual(block["base_fee_per_gas"], "1000000000")

        call = execute(["call", TOKEN, "decimals()(uint8)"], self.app)
        self.assertEqual(call["signature"], "decimals()(uint8)")
        self.assertEqual(call["result"], "[18]")

    def test_estimate_alias_matches_send_dry_run(self) -> None:
        self.add_wallet()
        result = execute(["estimate", DESTINATION, "0.1"], self.app)
        self.assertEqual(result["command"], "estimate")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["amount_base_units"], "100000000000000000")
        self.assertNotIn("send", [command[0] for command in self.runner.commands()])

    def test_contacts_add_list_resolve_and_remove(self) -> None:
        self.add_wallet()
        saved = execute(["contact", "add", "bob", DESTINATION], self.app)
        self.assertEqual(saved["address"], DESTINATION)
        listed = execute(["contact", "list"], self.app)
        self.assertEqual(listed["contacts"], [{"name": "bob", "address": DESTINATION}])

        self.assertEqual(execute(["balance", "bob"], self.app)["address"], DESTINATION)
        send = execute(["send", "bob", "0.1", "--dry-run"], self.app)
        self.assertEqual(send["to"], DESTINATION)

        removed = execute(["contact", "remove", "bob"], self.app)
        self.assertEqual(removed["name"], "bob")
        self.assertEqual(execute(["contact", "list"], self.app)["contacts"], [])

    def test_token_metadata_saved_list_and_allowance(self) -> None:
        self.add_wallet()
        info = execute(["token", "info", TOKEN], self.app)
        self.assertEqual(info["name"], "Test Token")
        self.assertEqual(info["symbol"], "TT")
        self.assertEqual(info["decimals"], 18)
        self.assertEqual(info["total_supply_raw"], "1234567890123456789")

        added = execute(["token", "add", TOKEN], self.app)
        self.assertEqual(added["symbol"], "TT")
        listed = execute(["token", "list"], self.app)
        self.assertEqual(len(listed["tokens"]), 1)
        self.assertEqual(listed["tokens"][0]["contract"], TOKEN)
        self.assertEqual(listed["tokens"][0]["balance"], "1.234567890123456789")

        allowance = execute(["token", "allowance", TOKEN, DESTINATION], self.app)
        self.assertEqual(allowance["spender"], DESTINATION)
        self.assertEqual(allowance["allowance"], "0.0000000000025")

        self.assertEqual(execute(["token", "remove", TOKEN], self.app)["contract"], TOKEN)
        self.assertEqual(execute(["token", "list"], self.app)["tokens"], [])
        with self.assertRaisesRegex(WalletCliError, "not saved"):
            execute(["token", "remove", TOKEN], self.app)

    def test_token_revoke_dry_run_and_broadcast(self) -> None:
        keystore = self.add_wallet()
        self.app = self.make_app(terminal=True)
        dry = execute(["token", "revoke", TOKEN, DESTINATION, "--dry-run"], self.app)
        self.assertTrue(dry["dry_run"])
        self.assertNotIn("send", [command[0] for command in self.runner.commands()])

        sent = execute(["token", "revoke", TOKEN, DESTINATION, "--yes"], self.app)
        self.assertEqual(sent["transaction_hash"], TX_HASH)
        send = self.runner.commands()[-1]
        self.assertEqual(send[0:5], ["send", TOKEN, "approve(address,uint256)", DESTINATION, "0"])
        self.assertIn(str(keystore), send)

    def test_tx_log_records_sends_and_lists_them(self) -> None:
        self.add_wallet()
        self.app = self.make_app(terminal=True)
        execute(["send", DESTINATION, "0.1", "--yes"], self.app)
        listed = execute(["tx", "list"], self.app)
        self.assertEqual(len(listed["transactions"]), 1)
        record = listed["transactions"][0]
        self.assertEqual(record["hash"], TX_HASH)
        self.assertEqual(record["kind"], "native")
        self.assertEqual(record["chain_id"], 1)
        self.assertEqual(record["to"], DESTINATION)

    def test_tx_watch_returns_pending_then_mined(self) -> None:
        self.runner.receipt_sequence = [
            "null",
            json.dumps({"transactionHash": TX_HASH, "status": "0x1"}),
        ]
        self.app.sleep = lambda _: None
        result = execute(["tx", "watch", TX_HASH], self.app)
        self.assertFalse(result["pending"])
        self.assertEqual(result["receipt"]["status"], "0x1")

        self.runner.receipt_sequence = ["null", "null"]
        self.app.watch_attempts = 2
        still_pending = execute(["tx", "watch", TX_HASH], self.app)
        self.assertTrue(still_pending["pending"])
        self.assertEqual(still_pending["attempts"], 2)

    def test_wallet_watch_is_read_only_and_verify_reports_health(self) -> None:
        watched = execute(["wallet", "watch", "cold", DESTINATION], self.app)
        self.assertTrue(watched["watch_only"])
        self.assertEqual(execute(["balance"], self.app)["address"], DESTINATION)

        terminal = self.make_app(terminal=True)
        with self.assertRaisesRegex(WalletCliError, "watch-only"):
            execute(["send", DESTINATION, "0.1", "--yes"], terminal)

        verified = execute(["wallet", "verify"], self.app)
        self.assertEqual(verified["wallets"][0]["alias"], "cold")
        self.assertTrue(verified["wallets"][0]["watch_only"])
        self.assertTrue(verified["wallets"][0]["valid"])

    def test_help_hides_advanced_commands_until_verbose(self) -> None:
        default = execute(["help"], self.app)
        self.assertIn("COMMANDS", default["text"])
        self.assertNotIn("config show", default["text"])
        self.assertNotIn("token add", default["text"])
        self.assertIn("help --verbose", default["text"])

        verbose = execute(["help", "--verbose"], self.app)
        self.assertTrue(verbose["verbose"])
        self.assertIn("config show", verbose["text"])
        self.assertIn("token add", verbose["text"])

        session = self.make_app()
        session.verbose = True
        self.assertIn("call CONTRACT", execute(["help"], session)["text"])

        gated = execute(["help", "config"], self.app)
        self.assertIn("advanced command", gated["text"])
        shown = execute(["help", "config", "--verbose"], self.app)
        self.assertIn("config show", shown["text"])

    def test_wallet_info_and_list_mark_watch_only_wallets(self) -> None:
        self.add_wallet("signer", ADDRESS)
        execute(["wallet", "watch", "cold", DESTINATION], self.app)
        info = execute(["wallet", "info", "cold"], self.app)
        self.assertTrue(info["watch_only"])
        self.assertIsNone(info["keystore"])
        listed = execute(["wallet", "list"], self.app)["wallets"]
        tags = {entry["alias"]: entry["watch_only"] for entry in listed}
        self.assertEqual(tags, {"signer": False, "cold": True})


if __name__ == "__main__":
    unittest.main()
