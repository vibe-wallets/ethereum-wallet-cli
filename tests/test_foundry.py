"""Mock-boundary tests for shell-free Foundry invocation and JSON output."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from evm_wallet.chains import BUILTIN_CHAINS
from evm_wallet.errors import FoundryError
from evm_wallet.foundry import CastClient, parse_integer_output, parse_rpc_integer, unwrap_cast_json


class CastClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="evm-wallet-cast-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_run_passes_argv_without_shell_and_uses_restricted_environment(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="  result\n", stderr="")
        observed: dict = {}

        def runner(command, **kwargs):
            observed["command"] = command
            observed.update(kwargs)
            return completed

        with patch.dict(
            os.environ,
            {
                "PATH": "/trusted/bin",
                "LANG": "C.UTF-8",
                "EVM_WALLET_RPC_URL": "https://secret.example.invalid/token",
                "PRIVATE_KEY": "never-forward-this",
            },
            clear=True,
        ):
            client = CastClient(self.directory, executable="cast", runner=runner)
            output = client.run(["wallet", "address", "a name; touch /tmp/nope"])

        self.assertEqual(output, "result")
        self.assertEqual(
            observed["command"],
            ["cast", "wallet", "address", "a name; touch /tmp/nope"],
        )
        self.assertEqual(observed["cwd"], self.directory)
        self.assertEqual(observed["text"], True)
        self.assertEqual(observed["stdin"], None)
        self.assertEqual(observed["stdout"], subprocess.PIPE)
        self.assertEqual(observed["stderr"], subprocess.PIPE)
        self.assertEqual(observed["check"], False)
        self.assertEqual(
            observed["env"],
            {
                "HOME": str(self.directory),
                "FOUNDRY_CONFIG": "/dev/null",
                "PATH": "/trusted/bin",
                "LANG": "C.UTF-8",
            },
        )

    def test_interactive_cast_inherits_terminal_instead_of_capturing_prompts(self) -> None:
        observed: dict = {}

        def runner(command, **kwargs):
            observed["command"] = command
            observed.update(kwargs)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        client = CastClient(self.directory, runner=runner)
        self.assertEqual(client.run(["wallet", "new"], interactive=True), "ok")
        self.assertEqual(observed["stdout"], subprocess.PIPE)
        self.assertEqual(observed["stderr"], subprocess.PIPE)

    def test_chain_id_mismatch_stops_before_broadcast(self) -> None:
        calls: list[list[str]] = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="0x7a70\n", stderr="")

        client = CastClient(self.directory, runner=runner)
        chain = BUILTIN_CHAINS["monad"]
        with self.assertRaisesRegex(FoundryError, "reported chain ID"):
            client.send(chain, ["--keystore", "/tmp/encrypted", "--value", "7"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], [client.executable, "chain-id", "--rpc-url", chain.rpc_url])

    def test_chain_match_allows_broadcast_with_expected_rpc_and_chain(self) -> None:
        calls: list[tuple[list[str], dict]] = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            stdout = (
                "143\n"
                if len(calls) == 1
                else '{"schema_version":1,"success":true,"data":{"hash":"0xabc"}}'
            )
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        client = CastClient(self.directory, runner=runner)
        chain = BUILTIN_CHAINS["monad"]
        output = client.send(chain, ["--keystore", "/tmp/encrypted", "--value", "7"])

        self.assertIn('"hash"', output)
        self.assertEqual(calls[0][0], [client.executable, "chain-id", "--rpc-url", chain.rpc_url])
        self.assertEqual(
            calls[1][0],
            [
                client.executable,
                "send",
                "--keystore",
                "/tmp/encrypted",
                "--value",
                "7",
                "--chain",
                "143",
                "--rpc-url",
                chain.rpc_url,
                "--json",
            ],
        )
        self.assertEqual(calls[1][1]["stdout"], subprocess.PIPE)
        self.assertEqual(calls[1][1]["stderr"], subprocess.PIPE)

    def test_cast_errors_are_reported_without_unbounded_output(self) -> None:
        def fail(command, **kwargs):
            return subprocess.CompletedProcess(command, 42, stdout="", stderr="bad input " * 200)

        with self.assertRaises(FoundryError) as caught:
            CastClient(self.directory, runner=fail).run(["balance", "0x" + "11" * 20])
        message = str(caught.exception)
        self.assertIn("status 42", message)
        self.assertLessEqual(len(message), 540)

    def test_foundry_output_parsers_accept_versioned_envelopes_and_hex_integers(self) -> None:
        payload = unwrap_cast_json(
            json.dumps({"schema_version": 1, "success": True, "data": {"hash": "0x123"}})
        )
        self.assertEqual(payload, {"hash": "0x123"})
        with self.assertRaises(FoundryError):
            unwrap_cast_json(
                '{"schema_version":1,"success":false,"data":null,"errors":["rejected"]}'
            )
        self.assertEqual(parse_integer_output("0x2a", "balance"), 42)
        self.assertEqual(parse_rpc_integer('["1000000000000000000"]', "balance"), 10**18)
        self.assertEqual(parse_rpc_integer("[18]", "decimals"), 18)
        for invalid in ("", "abc", "-1", "4.5", "0xZZ"):
            with self.subTest(invalid=invalid), self.assertRaises(FoundryError):
                parse_integer_output(invalid, "balance")

    def test_rpc_uint_parser_rejects_negative_bool_multiple_and_overflow_values(self) -> None:
        invalid_values = (
            "-1",
            "[-1]",
            "[true]",
            "[1,2]",
            str(1 << 256),
            f"[{1 << 256}]",
            "true",
            "[3.14]",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(FoundryError):
                parse_rpc_integer(value, "uint256")

    def test_trace_redacts_private_rpc_urls_and_clears_after_flush(self) -> None:
        from evm_wallet.chains import Chain

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="1", stderr="")

        secret_rpc = "https://rpc.example.invalid/key-like-token?auth=hidden"
        client = CastClient(self.directory, runner=runner)
        client.verify_chain(Chain("private", 1, secret_rpc))
        self.assertEqual(len(client.trace), 1)
        self.assertNotIn(secret_rpc, client.trace[0])
        self.assertIn("<redacted-rpc-url>", client.trace[0])

        trace_output = io.StringIO()
        with redirect_stderr(trace_output):
            client.flush_trace()
        self.assertIn("cast chain-id", trace_output.getvalue())
        self.assertIn("<redacted-rpc-url>", trace_output.getvalue())
        self.assertNotIn("hidden", trace_output.getvalue())
        self.assertEqual(client.trace, [])


if __name__ == "__main__":
    unittest.main()
