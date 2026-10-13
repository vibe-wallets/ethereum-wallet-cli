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
from evm_wallet.help import help_text
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
    whole_amount,
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

    def test_whole_amount_truncates_but_keeps_small_values_visible(self):
        self.assertEqual(whole_amount("2211253192.593614836340904018"), "2211253192")
        self.assertEqual(whole_amount("1000"), "1000")
        self.assertEqual(whole_amount("0"), "0")
        self.assertEqual(whole_amount("0.000000000000000001"), "<1")
        self.assertEqual(whole_amount("12.0"), "12")

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

    def test_table_right_aligns_the_columns_it_is_asked_to(self):
        rendered = table(
            [["97", "2211253252"], ["3", "218620885"]],
            ["ID", "STAKE"],
            width=40,
            right_align=("STAKE",),
        )
        self.assertEqual(
            rendered.splitlines(),
            [
                "ID       STAKE",
                "--  ----------",
                "97  2211253252",
                "3    218620885",
            ],
        )

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
        styled = style_help("NOTES\n  keep keys safe", enabled=True)
        self.assertIn("\x1b[1;36mNOTES\x1b[0m", styled)
        self.assertIn("  keep keys safe", styled)

    def test_style_help_colors_a_heading_with_a_lower_case_note(self):
        styled = style_help("STAKING (Monad and BNB Smart Chain)\n  stake validators", enabled=True)
        self.assertIn("\x1b[1;36mSTAKING (Monad and BNB Smart Chain)\x1b[0m", styled)
        self.assertIn("  stake validators", styled)

    def test_every_help_section_heading_is_colored(self):
        styled = style_help(help_text(), enabled=True)
        for heading in (
            "COMMANDS",
            "WALLETS",
            "TRANSFERS",
            "STAKING (Monad and BNB Smart Chain)",
            "INSPECTION",
            "UTILITIES",
        ):
            self.assertIn(f"\x1b[1;36m{heading}\x1b[0m", styled)
        # Left-margin prose stays plain, including lines that end with a colon.
        self.assertNotIn("\x1b[1;36mAmounts are exact decimal", styled)
        self.assertNotIn("\x1b[1;36mis an exact decimal", styled)

    def test_style_help_leaves_wrapped_prose_alone(self):
        prose = "is an exact decimal string such as 0.01. The command estimates gas first:"
        styled = style_help(f"SEND NATIVE COIN\n{prose}", enabled=True)
        self.assertIn("\x1b[1;36mSEND NATIVE COIN\x1b[0m", styled)
        self.assertIn(f"\n{prose}", styled)


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

    def test_status_gas_nonce_and_history_render_pretty(self):
        status = io.StringIO()
        _render_human(
            {
                "command": "status",
                "profile": "ethereum",
                "network": "mainnet",
                "chain_id": 1,
                "rpc_url": "https://ethereum-rpc.publicnode.com",
                "wallet": "daily",
                "address": "0x" + "11" * 20,
                "balance_native": "1.5",
            },
            status,
        )
        self.assertIn("STATUS", status.getvalue())
        self.assertIn("MAINNET · REAL FUNDS", status.getvalue())
        self.assertIn("Balance : 1.5", status.getvalue())
        self.assertNotIn("DELEGATIONS", status.getvalue())

        staked = io.StringIO()
        _render_human(
            {
                "command": "status",
                "profile": "monad",
                "network": "mainnet",
                "chain_id": 143,
                "rpc_url": "https://rpc.monad.xyz",
                "wallet": "daily",
                "address": "0x" + "11" * 20,
                "balance_native": "1.5",
                "delegations": [
                    {
                        "validator_id": 11,
                        "stake": "1",
                        "unclaimed_rewards": "0.5",
                        "pending_stake": "0",
                    }
                ],
            },
            staked,
        )
        self.assertIn("DELEGATIONS", staked.getvalue())
        self.assertIn("VALIDATOR", staked.getvalue())
        self.assertIn("0.5", staked.getvalue())

        bsc_staked = io.StringIO()
        _render_human(
            {
                "command": "status",
                "profile": "bsc",
                "network": "mainnet",
                "chain_id": 56,
                "rpc_url": "https://bsc-rpc.publicnode.com",
                "wallet": "daily",
                "address": "0x" + "11" * 20,
                "balance_native": "1.5",
                "delegations": [
                    {
                        "operator": "0x" + "bb" * 20,
                        "pooled_bnb": "3",
                        "commission": "9.00",
                        "pending_unbond_requests": 1,
                        "claimable_unbond_requests": 0,
                    }
                ],
            },
            bsc_staked,
        )
        self.assertIn("DELEGATIONS", bsc_staked.getvalue())
        self.assertIn("POOLED (BNB)", bsc_staked.getvalue())
        self.assertIn("9.00%", bsc_staked.getvalue())

        gas = io.StringIO()
        _render_human(
            {
                "command": "gas",
                "chain": "testnet",
                "chain_id": 11155111,
                "gas_price_wei": "1500000000",
                "gas_price_gwei": "1.5",
            },
            gas,
        )
        self.assertIn("GAS", gas.getvalue())
        self.assertIn("Gas price: 1.5 gwei", gas.getvalue())

        nonce = io.StringIO()
        _render_human(
            {
                "command": "nonce",
                "chain": "local",
                "address": "0x" + "22" * 20,
                "nonce": "7",
            },
            nonce,
        )
        self.assertIn("NONCE", nonce.getvalue())
        self.assertIn("Nonce  : 7", nonce.getvalue())

        history = io.StringIO()
        _render_human(
            {"command": "history", "count": 20, "entries": ["wallet list", "status"]},
            history,
        )
        self.assertIn("HISTORY", history.getvalue())
        self.assertIn("1  wallet list", history.getvalue())

    def test_stake_undelegate_preview_shows_scope_and_left_behind_rewards(self):
        output = io.StringIO()
        _render_human(
            {
                "command": "stake undelegate",
                "dry_run": True,
                "chain": "monad",
                "validator_id": "161",
                "amount": "1000 MON",
                "scope": "all active stake",
                "withdraw_id": "0",
                "pending_stake": "4 MON not undelegatable until it activates",
                "unclaimed_rewards": "3 MON not claimed; run `stake claim 161`",
                "estimated_gas": "200000",
            },
            output,
        )
        rendered = output.getvalue()
        self.assertIn("STAKE UNDELEGATE · TRANSACTION PREVIEW", rendered)
        self.assertIn("all active stake", rendered)
        self.assertIn("Unclaimed rewards", rendered)
        self.assertIn("stake claim 161", rendered)
        self.assertIn("Pending stake", rendered)

    def test_wallet_rename_and_delete_render_confirmations(self):
        renamed = io.StringIO()
        _render_human(
            {
                "command": "wallet rename",
                "old_alias": "primary",
                "alias": "daily",
                "address": "0x" + "11" * 20,
            },
            renamed,
        )
        self.assertIn("renamed to 'daily'", renamed.getvalue())

        deleted = io.StringIO()
        _render_human(
            {"command": "wallet delete", "alias": "daily", "address": "0x" + "11" * 20},
            deleted,
        )
        self.assertIn("deleted locally", deleted.getvalue())

    def test_staking_views_and_receipts_render(self):
        status = io.StringIO()
        _render_human(
            {
                "command": "stake status",
                "chain": "mainnet",
                "chain_id": 143,
                "address": "0x" + "11" * 20,
                "epoch": 7,
                "in_epoch_delay": False,
                "dust_threshold": "0.000000001 MON",
                "withdrawal_delay_epochs": 1,
                "delegations": [
                    {
                        "validator_id": 11,
                        "stake": "1",
                        "unclaimed_rewards": "2",
                        "pending_stake": "0",
                    }
                ],
            },
            status,
        )
        self.assertIn("STAKING STATUS", status.getvalue())
        self.assertIn("DELEGATIONS", status.getvalue())
        self.assertIn("11", status.getvalue())

        validators = io.StringIO()
        _render_human(
            {
                "command": "stake validators",
                "chain": "mainnet",
                "epoch": 2257,
                "active_only": True,
                "active_count": 196,
                "full": False,
                "validators": [
                    {
                        "validator_id": 3,
                        "status": "ok",
                        "stake": "218620885.432720435926133658",
                        "consensus_stake": "218620885.432720435926133658",
                        "snapshot_stake": "218620885.432720435926133658",
                        "commission": "15.00",
                        "auth_address": "0x" + "bb" * 20,
                    }
                ],
            },
            validators,
        )
        self.assertIn("VALIDATORS", validators.getvalue())
        self.assertIn("epoch 2257", validators.getvalue())
        self.assertIn("196 active", validators.getvalue())
        self.assertIn("STATUS", validators.getvalue())
        self.assertIn("15.00%", validators.getvalue())
        # Stake columns show whole MON; --json keeps the exact value.
        self.assertIn("218620885", validators.getvalue())
        self.assertNotIn("218620885.432720435926133658", validators.getvalue())
        header_line, stake_line = (
            line for line in validators.getvalue().splitlines() if line.startswith(("ID ", "3 "))
        )
        # Numbers end where their header ends: the stake column is right-aligned.
        self.assertEqual(
            header_line.index("STAKE (MON)") + len("STAKE (MON)"),
            stake_line.index("218620885") + len("218620885"),
        )
        self.assertIn(shorten_address("0x" + "bb" * 20), validators.getvalue())
        self.assertNotIn("SNAPSHOT (MON)", validators.getvalue())

        full = io.StringIO()
        _render_human(
            {
                "command": "stake validators",
                "chain": "mainnet",
                "epoch": 2257,
                "active_only": False,
                "active_count": 196,
                "eligible_count": 201,
                "full": True,
                "validators": [
                    {
                        "validator_id": 3,
                        "status": "inactive",
                        "stake": "1",
                        "consensus_stake": "1",
                        "snapshot_stake": "1",
                        "commission": "15.00",
                        "auth_address": "0x" + "bb" * 20,
                    }
                ],
            },
            full,
        )
        self.assertIn("201 eligible", full.getvalue())
        self.assertIn("SNAPSHOT (MON)", full.getvalue())
        self.assertIn("inactive", full.getvalue())
        self.assertIn("0x" + "bb" * 20, full.getvalue())

        bsc_validators = io.StringIO()
        _render_human(
            {
                "command": "stake validators",
                "chain": "mainnet",
                "validators": [
                    {
                        "operator": "0x" + "bb" * 20,
                        "consensus": "0x" + "cc" * 20,
                        "stake": "1",
                        "commission": "9.00",
                    }
                ],
            },
            bsc_validators,
        )
        self.assertIn("OPERATOR", bsc_validators.getvalue())
        self.assertIn("9.00%", bsc_validators.getvalue())

        preview = io.StringIO()
        _render_human(
            {
                "command": "stake delegate",
                "dry_run": True,
                "chain": "mainnet",
                "from_wallet": "primary",
                "from": "0x" + "11" * 20,
                "validator_id": "11",
                "amount": "1 MON",
                "estimated_gas": "51234",
            },
            preview,
        )
        self.assertIn("STAKE DELEGATE", preview.getvalue())
        self.assertIn("1 MON", preview.getvalue())

        receipt = io.StringIO()
        _render_human(
            {
                "command": "stake claim",
                "dry_run": False,
                "chain": "mainnet",
                "from_wallet": "primary",
                "from": "0x" + "11" * 20,
                "validator_id": "11",
                "estimated_gas": "51234",
                "wallet": "primary",
                "transaction_hash": "0x" + "aa" * 32,
            },
            receipt,
        )
        self.assertIn("Stake claim submitted", receipt.getvalue())
        self.assertIn("0x" + "aa" * 32, receipt.getvalue())


if __name__ == "__main__":
    unittest.main()
