"""Pretty human output and the clear command."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from evm_wallet.app import Application, execute
from evm_wallet.cli import _render_human, _run_one
from evm_wallet.human import (
    CLEAR_SCREEN,
    action_preview,
    color,
    color_enabled,
    display_width,
    format_transaction_receipt,
    key_value_rows,
    network_label,
    shorten_address,
    style_help,
    table,
)


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class ColorTests(unittest.TestCase):
    def test_color_is_disabled_for_redirected_output(self):
        self.assertFalse(color_enabled(io.StringIO()))
        self.assertEqual(color("x", "error", stream=io.StringIO()), "x")

    def test_color_respects_no_color_and_dumb_terminals(self):
        tty = TTY()
        with patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            self.assertTrue(color_enabled(tty))
        with patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True):
            self.assertFalse(color_enabled(tty))
        with patch.dict(os.environ, {"TERM": "dumb"}, clear=True):
            self.assertFalse(color_enabled(tty))

    def test_enabled_color_wraps_and_resets(self):
        self.assertEqual(color("boom", "error", enabled=True), "\x1b[1;31mboom\x1b[0m")
        self.assertEqual(color("", "error", enabled=True), "")


class LayoutTests(unittest.TestCase):
    def test_display_width_ignores_ansi_and_counts_wide_glyphs(self):
        self.assertEqual(display_width("\x1b[1mabc\x1b[0m"), 3)
        self.assertEqual(display_width("钱包"), 4)

    def test_shorten_address_keeps_the_edges(self):
        address = "0x" + "11" * 20
        self.assertEqual(shorten_address(address), address[:6] + "…" + address[-4:])
        self.assertEqual(shorten_address("0x1234"), "0x1234")

    def test_key_value_rows_align_labels_without_color(self):
        rendered = key_value_rows([("Alias", "daily"), ("Encrypted keystore", "/data/x")])
        self.assertEqual(
            rendered.splitlines(),
            ["Alias             : daily", "Encrypted keystore: /data/x"],
        )

    def test_key_value_rows_apply_optional_tone(self):
        rendered = key_value_rows([("State", "ok", "success")], enabled=True)
        self.assertIn("\x1b[1;32mok\x1b[0m", rendered)

    def test_table_aligns_columns_and_falls_back_when_narrow(self):
        address = "0x" + "11" * 20
        rendered = table([["daily", address], ["ops", "0x" + "22" * 20]], ["ALIAS", "ADDRESS"])
        self.assertIn("ALIAS", rendered)
        self.assertIn("daily", rendered)
        self.assertIn(address, rendered)

        narrow = table([["daily", address]], ["ALIAS", "ADDRESS"], width=10)
        self.assertEqual(narrow, f"ALIAS: daily\nADDRESS: {address}")

    def test_network_label_marks_mainnet_and_keeps_text_fallback(self):
        self.assertEqual(network_label("mainnet", enabled=False), "MAINNET · REAL FUNDS")
        self.assertEqual(network_label("testnet", enabled=False), "TESTNET")
        self.assertEqual(network_label("local", enabled=False), "LOCAL")

    def test_action_preview_and_receipt_include_the_key_fields(self):
        preview = action_preview(
            "SEND NATIVE · TRANSACTION PREVIEW",
            [("Network", network_label("testnet", enabled=False)), ("Amount", "1.0")],
            enabled=False,
        )
        self.assertIn("SEND NATIVE · TRANSACTION PREVIEW", preview)
        self.assertIn("Amount : 1.0", preview)

        signature = "0x" + "aa" * 32
        receipt = format_transaction_receipt(
            action="Transaction",
            network="mainnet",
            rows=[("To", "0x" + "22" * 20)],
            signature=signature,
            enabled=False,
        )
        self.assertIn("Transaction submitted", receipt)
        self.assertIn("MAINNET · REAL FUNDS", receipt)
        self.assertIn(f"Transaction: {signature}", receipt)

    def test_style_help_styles_only_headings(self):
        styled = style_help("Commands:\n  wallet list\n\nNOTES\n  keep keys safe", enabled=True)
        self.assertIn("\x1b[1;36mCommands:\x1b[0m", styled)
        self.assertIn("\x1b[1;36mNOTES\x1b[0m", styled)
        self.assertIn("  wallet list", styled)


class ClearAndRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="evm-wallet-human-")
        self.addCleanup(self.temporary.cleanup)

    def test_clear_command_returns_a_cleared_result_and_json_envelope(self):
        app = Application(Path(self.temporary.name) / "config", cast_executable="mock-cast")
        self.assertEqual(execute(["clear"], app), {"command": "clear", "cleared": True})

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = _run_one(["clear"], app, json_output=True)
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["cleared"])

    def test_clear_writes_a_screen_reset_only_to_a_terminal(self):
        tty = TTY()
        _render_human({"command": "clear"}, tty)
        self.assertEqual(tty.getvalue(), CLEAR_SCREEN)

        plain = io.StringIO()
        _render_human({"command": "clear"}, plain)
        self.assertEqual(plain.getvalue(), "")

    def test_balance_human_output_uses_a_title_and_aligned_rows(self):
        stdout = io.StringIO()
        _render_human(
            {
                "command": "balance",
                "chain": "mainnet",
                "address": "0x" + "11" * 20,
                "balance_native": "2.000000000000000001",
            },
            stdout,
        )
        text = stdout.getvalue()
        self.assertIn("NATIVE BALANCE", text)
        self.assertIn("Balance: 2.000000000000000001", text)
        self.assertIn("MAINNET · REAL FUNDS", text)


if __name__ == "__main__":
    unittest.main()
