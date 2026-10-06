"""Protect against lost wallet metadata when multiple CLI processes write."""

from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from evm_wallet.config import ConfigStore


def add_wallet_metadata(directory: str, worker: int):
    store = ConfigStore(directory)
    for index in range(5):
        alias = f"worker{worker}_{index}"
        metadata = {
            "keystore": f"wallets/{worker * 5 + index:032x}",
            "address": f"0x{worker * 5 + index:040x}",
        }
        store.update(lambda state: state["wallets"].update({alias: metadata}))


class ConcurrentConfigTests(unittest.TestCase):
    def test_parallel_cli_writes_preserve_all_wallet_metadata(self):
        with tempfile.TemporaryDirectory(prefix="wallet-config-concurrency-") as temporary:
            directory = str(Path(temporary) / "config")
            context = multiprocessing.get_context("spawn")
            processes = [
                context.Process(target=add_wallet_metadata, args=(directory, worker))
                for worker in range(4)
            ]
            try:
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(timeout=15)
                    self.assertEqual(process.exitcode, 0)
                state = ConfigStore(directory).load()
                self.assertEqual(
                    set(state["wallets"]),
                    {f"worker{worker}_{index}" for worker in range(4) for index in range(5)},
                )
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=5)
