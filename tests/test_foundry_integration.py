"""Opt-in Foundry/Anvil checks. These tests only use a temporary local chain."""

from __future__ import annotations

import json
import os
import pty
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from evm_wallet.config import ConfigStore

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
TOKEN = "0x0000000000000000000000000000000000001234"
FALSE_TOKEN = "0x0000000000000000000000000000000000001235"
PRIVATE_KEY_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ENABLED = (
    os.environ.get("WALLET_CLI_INTEGRATION") == "1"
    and shutil.which("cast") is not None
    and shutil.which("anvil") is not None
)


def _rpc(url: str, method: str, params: list[object]) -> object:
    request = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.loads(response.read())
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload.get("result")


def _static_erc20_runtime(balance: int, decimals: int = 18, transfer: bool = True) -> str:
    """Runtime bytecode with decimals/balanceOf and a configurable transfer result."""
    if not 0 <= decimals < 256:
        raise ValueError("decimals must fit uint8")
    # Dispatcher destinations: decimals JUMPDEST=0x29, balanceOf=0x34,
    # transfer=0x5e. It returns constant balance values and an ABI bool for
    # transfer, enough to exercise Cast simulation, signing and receipts.
    prefix = (
        "60003560e01c8063313ce56714602957806370a0823114603457"
        "8063a9059cbb14605e57"
        "60006000fd5b"
        f"60{decimals:02x}60005260206000f35b7f"
    )
    suffix = f"60005260206000f35b60{1 if transfer else 0:02x}60005260206000f3"
    return "0x" + prefix + balance.to_bytes(32, "big").hex() + suffix


def _run_cli(
    config_dir: Path,
    network: str,
    command: list[str],
    *,
    rpc_url: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment.pop("ETHEREUM_WALLET_CONFIG_DIR", None)
    environment.pop("MONAD_WALLET_CONFIG_DIR", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evm_wallet",
            "--config-dir",
            str(config_dir),
            "--network",
            network,
            "--rpc-url",
            rpc_url,
            "--json",
            *command,
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _run_interactive_cli(
    config_dir: Path,
    network: str,
    command: list[str],
    prompts: list[tuple[bytes, str]],
    *,
    rpc_url: str,
) -> tuple[int, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment.pop("ETHEREUM_WALLET_CONFIG_DIR", None)
    environment.pop("MONAD_WALLET_CONFIG_DIR", None)
    argv = [
        sys.executable,
        "-m",
        "evm_wallet",
        "--config-dir",
        str(config_dir),
        "--network",
        network,
        "--rpc-url",
        rpc_url,
        *command,
    ]
    pid, terminal = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, argv, environment)

    output = bytearray()
    sent: set[int] = set()
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([terminal], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(terminal, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                for index, (marker, response) in enumerate(prompts):
                    if index not in sent and marker.lower() in output.lower():
                        # Foundry changes the terminal echo mode asynchronously
                        # after printing the getpass prompt.
                        time.sleep(0.05)
                        os.write(terminal, response.encode("utf-8") + b"\n")
                        sent.add(index)
            child, status = os.waitpid(pid, os.WNOHANG)
            if child:
                code = os.waitstatus_to_exitcode(status)
                return code, output.decode("utf-8", errors="replace")
        else:
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
            raise AssertionError(
                f"interactive CLI timed out; output so far: {output.decode(errors='replace')}"
            )

        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), output.decode("utf-8", errors="replace")
    finally:
        try:
            os.close(terminal)
        except OSError:
            pass


@unittest.skipUnless(ENABLED, "set WALLET_CLI_INTEGRATION=1 and install Foundry cast/anvil")
class FoundryAnvilIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.rpc_url = f"http://127.0.0.1:{cls.port}"
        cls.anvil = subprocess.Popen(
            [
                "anvil",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--chain-id",
                "31337",
                "--silent",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.anvil.poll() is not None:
                raise RuntimeError("Anvil exited before the local test chain became available")
            try:
                if _rpc(cls.rpc_url, "eth_chainId", []) == "0x7a69":
                    break
            except (OSError, urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            cls.anvil.terminate()
            raise RuntimeError("Anvil did not start within 15 seconds")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.anvil.terminate()
        try:
            cls.anvil.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.anvil.kill()
            cls.anvil.wait(timeout=5)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="evm-wallet-anvil-")
        self.addCleanup(self.temp.cleanup)
        self.config_dir = Path(self.temp.name) / "config"
        self.store = ConfigStore(self.config_dir)
        self.store.update(lambda state: None)

    def test_real_cast_native_balance_and_erc20_uint_decoding(self) -> None:
        balance = _run_cli(self.config_dir, "local", ["balance", ACCOUNT], rpc_url=self.rpc_url)
        self.assertEqual(balance.returncode, 0, balance.stderr)
        balance_result = json.loads(balance.stdout)
        self.assertTrue(balance_result["ok"])
        self.assertEqual(balance_result["balance_native"], "10000")
        self.assertEqual(balance_result["balance_base_units"], "10000000000000000000000")

        _rpc(
            self.rpc_url,
            "anvil_setCode",
            [TOKEN, _static_erc20_runtime(1_234_500_000_000_000_000, decimals=18)],
        )
        token_balance = _run_cli(
            self.config_dir, "local", ["token", "balance", TOKEN, ACCOUNT], rpc_url=self.rpc_url
        )
        self.assertEqual(token_balance.returncode, 0, token_balance.stderr)
        token_result = json.loads(token_balance.stdout)
        self.assertTrue(token_result["ok"])
        self.assertEqual(token_result["decimals"], 18)
        self.assertEqual(token_result["balance_raw"], "1234500000000000000")
        self.assertEqual(token_result["balance"], "1.2345")

    def test_actual_chain_id_mismatch_fails_before_read_call(self) -> None:
        result = _run_cli(self.config_dir, "mainnet", ["balance", ACCOUNT], rpc_url=self.rpc_url)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr.splitlines()[0])
        self.assertFalse(error["ok"])
        self.assertIn("reported chain ID 31337", error["error"])
        self.assertIn("cast chain-id", result.stderr)
        self.assertNotIn(self.rpc_url, result.stderr)

    def test_foundry_creates_and_imports_real_encrypted_keystores_in_a_tty(self) -> None:
        create_password = "local create passphrase"
        create = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", "wallet new created"],
            [(b"Enter secret:", create_password)],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(create[0], 0, create[1])
        self.assertIn("Wallet 'created' is ready", create[1])
        self.assertNotIn(create_password, create[1])

        scalar = 0
        while scalar == 0 or scalar >= PRIVATE_KEY_ORDER:
            scalar = int.from_bytes(secrets.token_bytes(32), "big")
        private_key = f"0x{scalar:064x}"
        import_password = "local import passphrase"
        imported = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", "wallet import imported"],
            [
                (b"private key:", private_key),
                (b"Enter password:", import_password),
            ],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(imported[0], 0, imported[1])
        self.assertIn("Wallet 'imported' is ready", imported[1])
        self.assertNotIn(private_key, imported[1])
        self.assertNotIn(import_password, imported[1])

        state = self.store.load()
        self.assertEqual(state["default_wallet"], "created")
        self.assertEqual(set(state["wallets"]), {"created", "imported"})
        for wallet in state["wallets"].values():
            keystore = self.store.keystore_path(wallet)
            document = json.loads(keystore.read_text(encoding="utf-8"))
            self.assertEqual(keystore.stat().st_mode & 0o777, 0o600)
            crypto = document.get("crypto", document.get("Crypto"))
            self.assertIsInstance(crypto, dict)
            self.assertNotIn(private_key[2:], keystore.read_text(encoding="utf-8"))

        default_result = _run_cli(
            self.config_dir, "local", ["wallet", "default", "imported"], rpc_url=self.rpc_url
        )
        self.assertEqual(default_result.returncode, 0, default_result.stderr)
        state = self.store.load()
        imported_address = state["wallets"]["imported"]["address"]
        self.assertEqual(state["default_wallet"], "imported")
        _rpc(self.rpc_url, "anvil_setBalance", [imported_address, hex(100 * 10**18)])

        destination = "0x0000000000000000000000000000000000005678"
        balance_before = int(_rpc(self.rpc_url, "eth_getBalance", [imported_address, "latest"]), 16)
        nonce_before = int(
            _rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16
        )
        dry_run = _run_cli(
            self.config_dir,
            "local",
            ["send", destination, "0.1", "--dry-run"],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertTrue(dry_payload["dry_run"])
        self.assertEqual(dry_payload["amount_base_units"], "100000000000000000")
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16),
            nonce_before,
        )
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getBalance", [imported_address, "latest"]), 16),
            balance_before,
        )

        wrong_password = "definitely not the keystore password"
        rejected_send = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", f"send {destination} 0.1 --yes"],
            [(b"password:", wrong_password)],
            rpc_url=self.rpc_url,
        )
        self.assertNotEqual(rejected_send[0], 0)
        self.assertNotIn(wrong_password, rejected_send[1])
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16),
            nonce_before,
        )
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getBalance", [imported_address, "latest"]), 16),
            balance_before,
        )

        native_send = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", f"send {destination} 0.1 --yes"],
            [(b"password:", import_password)],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(native_send[0], 0, native_send[1])
        self.assertNotIn(import_password, native_send[1])
        self.assertIn("Transaction submitted on local", native_send[1])
        native_match = re.search(
            r"Transaction submitted on local: (0x[0-9a-fA-F]{64})", native_send[1]
        )
        self.assertIsNotNone(native_match, native_send[1])
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getBalance", [destination, "latest"]), 16),
            10**17,
        )
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16), 1
        )

        inspected = _run_cli(
            self.config_dir, "local", ["tx", "inspect", native_match.group(1)], rpc_url=self.rpc_url
        )
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        inspected_result = json.loads(inspected.stdout)
        self.assertFalse(inspected_result["pending"])
        self.assertIn(inspected_result["receipt"]["status"], ("0x1", "1", 1))

        _rpc(
            self.rpc_url,
            "anvil_setCode",
            [TOKEN, _static_erc20_runtime(1_234_500_000_000_000_000, decimals=18, transfer=True)],
        )
        _rpc(
            self.rpc_url,
            "anvil_setCode",
            [FALSE_TOKEN, _static_erc20_runtime(0, decimals=18, transfer=False)],
        )
        before_token_nonce = int(
            _rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16
        )
        false_transfer = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", f"token send {FALSE_TOKEN} {destination} 1.25 --yes"],
            [],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(false_transfer[0], 1, false_transfer[1])
        self.assertIn("returned false", false_transfer[1])
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16),
            before_token_nonce,
        )

        token_dry_run = _run_cli(
            self.config_dir,
            "local",
            ["token", "send", TOKEN, destination, "1.25", "--dry-run"],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(token_dry_run.returncode, 0, token_dry_run.stderr)
        self.assertEqual(json.loads(token_dry_run.stdout)["amount_raw"], "1250000000000000000")
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16),
            before_token_nonce,
        )

        token_send = _run_interactive_cli(
            self.config_dir,
            "local",
            ["-c", f"token send {TOKEN} {destination} 1.25 --yes"],
            [(b"password:", import_password)],
            rpc_url=self.rpc_url,
        )
        self.assertEqual(token_send[0], 0, token_send[1])
        self.assertNotIn(import_password, token_send[1])
        self.assertIn("Token transaction submitted on local", token_send[1])
        token_match = re.search(
            r"Token transaction submitted on local: (0x[0-9a-fA-F]{64})", token_send[1]
        )
        self.assertIsNotNone(token_match, token_send[1])
        self.assertEqual(
            int(_rpc(self.rpc_url, "eth_getTransactionCount", [imported_address, "latest"]), 16),
            before_token_nonce + 1,
        )
        token_receipt = _run_cli(
            self.config_dir, "local", ["tx", "inspect", token_match.group(1)], rpc_url=self.rpc_url
        )
        self.assertEqual(token_receipt.returncode, 0, token_receipt.stderr)
        self.assertFalse(json.loads(token_receipt.stdout)["pending"])


if __name__ == "__main__":
    unittest.main()
