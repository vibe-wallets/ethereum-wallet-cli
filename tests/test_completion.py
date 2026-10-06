"""Tab-completion candidate tests."""

from __future__ import annotations

import unittest

from evm_wallet.completion import complete_candidates


class CompletionTests(unittest.TestCase):
    def test_first_word_completes_from_the_command_index(self):
        self.assertIn("wallet", complete_candidates([], "wal"))
        self.assertEqual(complete_candidates([], "wallet"), ["wallet"])
        self.assertIn("status", complete_candidates([], "stat"))
        self.assertEqual(complete_candidates([], "zzz"), [])

    def test_wallet_subcommands_and_alias_arguments(self):
        self.assertIn("rename", complete_candidates(["wallet"], ""))
        self.assertIn("delete", complete_candidates(["wallet"], "de"))
        self.assertEqual(
            complete_candidates(["wallet", "use"], "", ["daily", "savings"]),
            ["daily", "savings"],
        )
        self.assertEqual(
            complete_candidates(["wallet", "delete"], "sav", ["daily", "savings"]),
            ["savings"],
        )
        # A new alias argument is free text, so there is nothing to complete.
        self.assertEqual(complete_candidates(["wallet", "rename", "daily"], ""), [])

    def test_chain_networks_and_token_and_tx_subcommands(self):
        self.assertEqual(complete_candidates(["chain"], ""), ["info", "list"])
        self.assertEqual(
            complete_candidates(["chain", "info"], "", []),
            ["local", "mainnet", "testnet"],
        )
        self.assertEqual(complete_candidates(["token"], ""), ["balance", "send"])
        self.assertEqual(complete_candidates(["tx"], ""), ["inspect"])

    def test_transfer_flags_complete_only_after_a_dash(self):
        self.assertEqual(complete_candidates(["send"], ""), [])
        self.assertEqual(
            complete_candidates(["send", "0xabc"], "--d"),
            ["--dry-run"],
        )
        self.assertEqual(
            complete_candidates(["token", "send", "0xtoken", "0xdest", "1"], "--"),
            ["--dry-run", "--yes"],
        )

    def test_help_topics_and_read_aliases(self):
        self.assertIn("wallet", complete_candidates(["help"], ""))
        self.assertIn("status", complete_candidates(["help"], "sta"))
        self.assertEqual(
            complete_candidates(["address"], "", ["daily", "ops"]),
            ["daily", "ops"],
        )
        self.assertEqual(complete_candidates(["nonce"], "d", ["daily"]), ["daily"])
        self.assertEqual(complete_candidates(["balance"], "", []), [])


if __name__ == "__main__":
    unittest.main()
