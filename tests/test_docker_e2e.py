"""Opt-in end-to-end tests through the published Docker wallet launchers.

Set ``WALLET_CLI_DOCKER_E2E=1`` to run these tests. The selected image is pulled
before any launcher starts. Integration traffic uses two owned Docker networks
with disposable Anvil nodes configured to report the real mainnet chain IDs; no
public RPC endpoint or live-funded wallet is used; test funds exist only on Anvil.
"""

from __future__ import annotations

import json
import os
import pty
import re
import secrets
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "ghcr.io/vibe-wallets/ethereum-wallet-cli:main"
LOCAL_IMAGE = "ethereum-wallet-cli:local"
IMAGE = os.environ.get("WALLET_CLI_DOCKER_E2E_IMAGE", DEFAULT_IMAGE)
ENABLED = os.environ.get("WALLET_CLI_DOCKER_E2E") == "1"

TOKEN = "0x0000000000000000000000000000000000001234"
FALSE_TOKEN = "0x0000000000000000000000000000000000001235"
DESTINATION = "0x0000000000000000000000000000000000005678"
TOKEN_INITIAL_BALANCE = 12_345_000_000_000_000_000
TOKEN_RUNTIME = (
    (ROOT / "tests" / "fixtures" / "TestToken.runtime.hex").read_text(encoding="utf-8").strip()
)
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _new_test_private_key() -> str:
    """Create an ephemeral valid signing scalar for Foundry's import prompt."""
    scalar = secrets.randbelow(SECP256K1_ORDER - 1) + 1
    return f"0x{scalar:064x}"


def _run_docker(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"docker {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def _static_erc20_runtime(balance: int, decimals: int = 18, transfer: bool = True) -> str:
    """Return tiny runtime bytecode for decimals, balanceOf and transfer calls."""
    if not 0 <= decimals < 256:
        raise ValueError("decimals must fit uint8")
    prefix = (
        "60003560e01c8063313ce56714602957806370a0823114603457"
        "8063a9059cbb14605e57"
        "60006000fd5b"
        f"60{decimals:02x}60005260206000f35b7f"
    )
    suffix = f"60005260206000f35b60{1 if transfer else 0:02x}60005260206000f3"
    return "0x" + prefix + balance.to_bytes(32, "big").hex() + suffix


def _parse_cast_number(value: str) -> int:
    text = value.strip().splitlines()[0].strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = text
    if isinstance(decoded, str):
        text = decoded
    text = text.split()[0]
    return int(text, 16 if text.lower().startswith("0x") else 10)


def _json_error(stderr: str) -> dict[str, object]:
    line = next(line for line in stderr.splitlines() if line.lstrip().startswith("{"))
    result = json.loads(line)
    if not isinstance(result, dict):
        raise AssertionError(f"expected a JSON error object, got {result!r}")
    return result


class DockerAnvilSandbox:
    """Owns a Docker network and one or more short-lived Anvil containers."""

    def __init__(self, image: str):
        suffix = uuid.uuid4().hex[:10]
        self.network = f"wallet-cli-e2e-{suffix}"
        self.image = image
        self.containers: dict[str, str] = {}

    def __enter__(self) -> DockerAnvilSandbox:
        _run_docker("network", "create", self.network)
        return self

    def start_anvil(self, alias: str, chain_id: int) -> str:
        name = f"{self.network}-{alias}"
        _run_docker(
            "run",
            "--detach",
            "--name",
            name,
            "--network",
            self.network,
            "--network-alias",
            alias,
            "--entrypoint",
            "anvil",
            self.image,
            "--host",
            "0.0.0.0",
            "--port",
            "8545",
            "--chain-id",
            str(chain_id),
            "--silent",
        )
        self.containers[alias] = name
        self._wait_for_anvil(name, chain_id)
        return name

    def _wait_for_anvil(self, name: str, chain_id: int) -> None:
        deadline = time.monotonic() + 30
        last_error = "not queried"
        while time.monotonic() < deadline:
            state = _run_docker("inspect", "--format", "{{.State.Running}}", name).stdout.strip()
            if state != "true":
                logs = subprocess.run(
                    ["docker", "logs", name], text=True, capture_output=True, check=False
                )
                raise AssertionError(f"Anvil container exited: {logs.stdout}\n{logs.stderr}")
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "cast",
                    "chain-id",
                    "--rpc-url",
                    "http://127.0.0.1:8545",
                ],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                actual = _parse_cast_number(result.stdout)
                if actual != chain_id:
                    raise AssertionError(f"Anvil reported chain ID {actual}, expected {chain_id}.")
                return
            last_error = result.stderr.strip()
            time.sleep(0.2)
        raise AssertionError(f"Anvil did not become ready; last Cast error: {last_error}")

    def cast_rpc(self, alias: str, method: str, *params: str) -> str:
        container = self.containers[alias]
        return _run_docker(
            "exec",
            container,
            "cast",
            "rpc",
            method,
            *params,
            "--rpc-url",
            "http://127.0.0.1:8545",
        ).stdout.strip()

    def prepare_test_account(self, alias: str, address: str) -> None:
        self.cast_rpc(alias, "anvil_setBalance", address, f"0x{10_000 * 10**18:x}")
        self.cast_rpc(alias, "anvil_setCode", TOKEN, TOKEN_RUNTIME)
        owner_slot = _run_docker(
            "exec",
            self.containers[alias],
            "cast",
            "index",
            "address",
            address,
            "0",
        ).stdout.strip()
        self.cast_rpc(
            alias,
            "anvil_setStorageAt",
            TOKEN,
            owner_slot,
            f"0x{TOKEN_INITIAL_BALANCE:064x}",
        )
        self.cast_rpc(alias, "anvil_setCode", FALSE_TOKEN, _static_erc20_runtime(0, transfer=False))

    def transaction_count(self, alias: str, address: str) -> int:
        result = self.cast_rpc(alias, "eth_getTransactionCount", address, "latest")
        return _parse_cast_number(result)

    def native_balance(self, alias: str, address: str) -> int:
        result = self.cast_rpc(alias, "eth_getBalance", address, "latest")
        return _parse_cast_number(result)

    def token_balance(self, alias: str, address: str) -> int:
        result = _run_docker(
            "exec",
            self.containers[alias],
            "cast",
            "call",
            TOKEN,
            "balanceOf(address)(uint256)",
            address,
            "--rpc-url",
            "http://127.0.0.1:8545",
        ).stdout.strip()
        return _parse_cast_number(result)

    def close(self) -> None:
        for name in self.containers.values():
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True, check=False)

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class LauncherShell:
    """PTY driver that exercises the exact interactive launcher and hides secrets."""

    PROMPT = re.compile(rb"(?:ethereum|monad)\[[^\]]*\]\([^)]*\)> $")

    def __init__(self, argv: list[str], environment: dict[str, str]):
        self.pid, self.terminal = pty.fork()
        self.output = bytearray()
        self.closed = False
        if self.pid == 0:
            os.execve(argv[0], argv, environment)
        self._wait_for_prompt(0, timeout=60)

    def _read_chunk(self, timeout: float = 0.2) -> None:
        ready, _, _ = select.select([self.terminal], [], [], timeout)
        if not ready:
            return
        try:
            chunk = os.read(self.terminal, 65536)
        except OSError:
            return
        if chunk:
            self.output.extend(chunk)

    def _wait_for_prompt(
        self,
        start: int,
        *,
        prompts: list[tuple[bytes, str]] | None = None,
        timeout: int = 45,
    ) -> str:
        pending = list(prompts or [])
        sent: set[int] = set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            section = bytes(self.output[start:])
            lower = section.lower()
            for index, (marker, response) in enumerate(pending):
                if index not in sent and marker.lower() in lower:
                    # Foundry switches terminal echo off after displaying getpass prompts.
                    time.sleep(0.05)
                    os.write(self.terminal, response.encode("utf-8") + b"\n")
                    sent.add(index)
                    break
            if self.PROMPT.search(section):
                missing = [
                    pending[i][0].decode(errors="replace")
                    for i in range(len(pending))
                    if i not in sent
                ]
                if missing:
                    raise AssertionError(f"shell returned before prompts {missing!r}: {section!r}")
                return section.decode("utf-8", errors="replace")
            self._read_chunk()
            child, status = os.waitpid(self.pid, os.WNOHANG)
            if child:
                self.closed = True
                raise AssertionError(
                    f"wallet shell exited unexpectedly ({os.waitstatus_to_exitcode(status)}):\n"
                    f"{bytes(self.output).decode(errors='replace')}"
                )
        raise AssertionError(
            f"wallet shell timed out waiting for its prompt:\n"
            f"{bytes(self.output[start:]).decode(errors='replace')}"
        )

    def command(self, text: str, *, prompts: list[tuple[bytes, str]] | None = None) -> str:
        start = len(self.output)
        os.write(self.terminal, text.encode("utf-8") + b"\n")
        result = self._wait_for_prompt(start, prompts=prompts)
        if "[wrapper]" not in result:
            raise AssertionError(f"command did not print its wrapper trace: {text!r}\n{result}")
        if (
            "[wrapper] /usr/local/bin/cast " not in result
            and "No external command ran" not in result
        ):
            raise AssertionError(f"local command omitted its no-external-command trace: {text!r}")
        return result

    def close(self) -> None:
        if self.closed:
            return
        try:
            os.write(self.terminal, b"exit\n")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                child, status = os.waitpid(self.pid, os.WNOHANG)
                if child:
                    self.closed = True
                    break
                self._read_chunk(timeout=0.1)
            if not self.closed:
                os.kill(self.pid, signal.SIGTERM)
                os.waitpid(self.pid, 0)
                self.closed = True
        except (OSError, ChildProcessError, ProcessLookupError):
            self.closed = True
        finally:
            try:
                os.close(self.terminal)
            except OSError:
                pass

    def __enter__(self) -> LauncherShell:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


@unittest.skipUnless(ENABLED, "set WALLET_CLI_DOCKER_E2E=1 to run pulled-image Docker E2E tests")
class DockerLauncherEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise RuntimeError("WALLET_CLI_DOCKER_E2E=1 requires the Docker CLI and daemon.")
        if IMAGE == LOCAL_IMAGE:
            # The local developer target builds this tag before entering the test suite.
            _run_docker("image", "inspect", IMAGE)
        else:
            # Deliberately fail on pull errors. E2E must exercise the requested image,
            # never silently fall back to a stale cache or build from this checkout.
            _run_docker("pull", IMAGE, timeout=600)
        cls.image = IMAGE

    def test_real_launchers_run_encrypted_wallet_and_transaction_workflows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wallet-cli-docker-e2e-") as temporary:
            root = Path(temporary)
            config_dirs = {profile: root / f"{profile}-config" for profile in ("ethereum", "monad")}
            with DockerAnvilSandbox(self.image) as sandbox:
                sandbox.start_anvil("anvil-ethereum", 1)
                sandbox.start_anvil("anvil-monad", 143)
                private_key = _new_test_private_key()
                imported_address: str | None = None
                generated_ethereum: str | None = None

                for profile, chain_id, network_alias in (
                    ("ethereum", 1, "anvil-ethereum"),
                    ("monad", 143, "anvil-monad"),
                ):
                    with self.subTest(profile=profile):
                        current_address = self._exercise_profile(
                            profile,
                            chain_id,
                            network_alias,
                            sandbox,
                            private_key,
                            self._launcher_environment(
                                profile,
                                config_dirs,
                                sandbox.network,
                                network_alias,
                            ),
                            config_dirs[profile],
                        )
                        wallet_state = json.loads(
                            (config_dirs[profile] / "config.json").read_text(encoding="utf-8")
                        )
                        self.assertEqual(set(wallet_state["wallets"]), {"generated", "imported"})
                        if profile == "ethereum":
                            generated_ethereum = wallet_state["wallets"]["generated"]["address"]
                            imported_address = current_address
                        else:
                            self.assertIsNotNone(generated_ethereum)
                            self.assertNotEqual(
                                generated_ethereum,
                                wallet_state["wallets"]["generated"]["address"],
                            )
                            self.assertEqual(imported_address, current_address)

                # Each command uses the other chain's isolated node to prove that
                # the launcher's configured mainnet ID is checked before RPC reads.
                mismatch_env = self._launcher_environment(
                    "ethereum", config_dirs, sandbox.network, "anvil-monad"
                )
                mismatch = self._run_one_shot("ethereum", mismatch_env, "balance", json_output=True)
                self.assertNotEqual(mismatch.returncode, 0, mismatch.stderr)
                self.assertEqual(mismatch.stdout, "")
                error = _json_error(mismatch.stderr)
                self.assertFalse(error["ok"])
                self.assertIn("reported chain ID 143", error["error"])
                self.assertLess(
                    mismatch.stderr.index("reported chain ID"), mismatch.stderr.index("[wrapper]")
                )
                self.assertIn("cast chain-id", mismatch.stderr)
                self.assertNotIn("anvil-monad:8545", mismatch.stderr)
                self._assert_cast_sequence(mismatch.stderr, ["chain-id"])

    def _launcher_environment(
        self,
        profile: str,
        config_dirs: dict[str, Path],
        docker_network: str,
        rpc_alias: str,
    ) -> dict[str, str]:
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith(("ETHEREUM_WALLET_", "MONAD_WALLET_")):
                environment.pop(name)
        environment.update(
            ETHEREUM_WALLET_CONFIG_DIR=str(config_dirs["ethereum"]),
            MONAD_WALLET_CONFIG_DIR=str(config_dirs["monad"]),
            ETHEREUM_WALLET_IMAGE=self.image,
            MONAD_WALLET_IMAGE=self.image,
            ETHEREUM_WALLET_NETWORK="mainnet",
            MONAD_WALLET_NETWORK="mainnet",
            ETHEREUM_WALLET_RPC_URL=f"http://{rpc_alias}:8545",
            MONAD_WALLET_RPC_URL=f"http://{rpc_alias}:8545",
            ETHEREUM_WALLET_DOCKER_NETWORK=docker_network,
            MONAD_WALLET_DOCKER_NETWORK=docker_network,
        )
        # The other profile's variables are intentionally present so the launcher's
        # allowlist and configuration isolation are exercised on every invocation.
        self.assertIn(profile, {"ethereum", "monad"})
        return environment

    def _exercise_profile(
        self,
        profile: str,
        chain_id: int,
        node_alias: str,
        sandbox: DockerAnvilSandbox,
        private_key: str,
        environment: dict[str, str],
        config_dir: Path,
    ) -> str:
        launcher = ROOT / "scripts" / f"{profile}-wallet-cli"
        password = f"e2e-{profile}-wallet-passphrase"
        wrong_password = f"wrong-{profile}-passphrase"

        with LauncherShell([str(launcher)], environment) as shell:
            initial = shell.command("wallet list")
            self.assertIn("No wallets", initial)
            self.assertIn("No external command ran", initial)

            help_output = shell.command("help")
            self.assertIn("Commands:", help_output)
            self.assertIn("No external command ran", help_output)

            cleared = shell.command("clear")
            self.assertIn("No external command ran", cleared)

            created = shell.command(
                "wallet new generated",
                prompts=[(b"Enter secret:", password)],
            )
            self.assertIn("Wallet 'generated' is ready", created)
            self.assertLess(
                created.index("Wallet 'generated' is ready"), created.index("[wrapper]")
            )
            self.assertNotIn(password, created)
            self.assertIn("cast wallet new", created)

            imported = shell.command(
                "wallet import imported",
                prompts=[(b"private key:", private_key), (b"Enter password:", password)],
            )
            self.assertIn("Wallet 'imported' is ready", imported)
            self.assertLess(
                imported.index("Wallet 'imported' is ready"), imported.index("[wrapper]")
            )
            self.assertNotIn(private_key, imported)
            self.assertNotIn(password, imported)
            self.assertIn("cast wallet import", imported)

            self.assertTrue(config_dir.is_dir())
            self.assertEqual(config_dir.stat().st_mode & 0o777, 0o700)
            state = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(set(state["wallets"]), {"generated", "imported"})
            self.assertEqual(state["default_wallet"], "generated")
            account = state["wallets"]["imported"]["address"]
            sandbox.prepare_test_account(node_alias, account)
            for metadata in state["wallets"].values():
                keystore = config_dir / metadata["keystore"]
                document = json.loads(keystore.read_text(encoding="utf-8"))
                self.assertEqual(keystore.stat().st_mode & 0o777, 0o600)
                self.assertIsInstance(document.get("crypto", document.get("Crypto")), dict)
                self.assertNotIn(private_key[2:].lower(), keystore.read_text().lower())

            listed = shell.command("wallet list")
            self.assertIn("generated", listed)
            self.assertIn("imported", listed)
            self.assertIn("[default]", listed)
            self.assertIn("[current]", listed)
            self.assertIn("No external command ran", listed)

            used = shell.command("wallet use imported")
            self.assertIn("Wallet 'imported' selected", used)
            self.assertIn("No external command ran", used)
            address = shell.command("address")
            self.assertIn(account.lower(), address.lower())
            self.assertIn("No external command ran", address)
            defaulted = shell.command("wallet default imported")
            self.assertIn("Wallet 'imported' selected", defaulted)
            info = shell.command("wallet info")
            self.assertIn("Alias", info)
            self.assertIn("imported", info)
            self.assertIn("Encrypted keystore", info)
            self.assertIn("No external command ran", info)

            chain_list = shell.command("chain list")
            self.assertIn(f"mainnet: chain {chain_id}", chain_list)
            self.assertIn(
                "testnet: chain 11155111" if profile == "ethereum" else "testnet: chain 10143",
                chain_list,
            )
            chain_info = shell.command("chain info")
            self.assertIn("mainnet", chain_info)
            self.assertIn(str(chain_id), chain_info)
            self.assertIn("No external command ran", chain_info)
            other_profile = "monad" if profile == "ethereum" else "ethereum"
            rejected_chain = shell.command(f"chain info {other_profile}")
            self.assertIn("not available", rejected_chain)
            self.assertIn("No external command ran", rejected_chain)

            balance = shell.command("balance")
            self.assertIn("native balance", balance.lower())
            self.assertIn(account.lower(), balance.lower())
            self.assertIn("mainnet", balance.lower())
            self.assertIn("10000", balance)
            self._assert_cast_sequence(balance, ["chain-id", "rpc"])

            token_balance = shell.command(f"token balance {TOKEN}")
            self.assertIn("token balance", token_balance.lower())
            self.assertIn(account.lower(), token_balance.lower())
            self.assertIn("mainnet", token_balance.lower())
            self.assertIn("12.345", token_balance)
            self._assert_cast_sequence(token_balance, ["chain-id", "call", "chain-id", "call"])
            self.assertEqual(sandbox.token_balance(node_alias, account), TOKEN_INITIAL_BALANCE)

            initial_nonce = sandbox.transaction_count(node_alias, account)
            initial_native_balance = sandbox.native_balance(node_alias, account)
            dry_run = shell.command(f"send {DESTINATION} 0.1 --dry-run")
            self.assertIn("transaction preview", dry_run.lower())
            self.assertIn("estimated gas", dry_run.lower())
            self._assert_cast_sequence(dry_run, ["chain-id", "estimate"])
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce)
            self.assertEqual(sandbox.native_balance(node_alias, account), initial_native_balance)

            cancelled = shell.command(
                f"send {DESTINATION} 0.05",
                prompts=[(b"Type 'yes' to continue:", "no")],
            )
            self.assertIn("Transaction cancelled", cancelled)
            self.assertLess(cancelled.index("Transaction cancelled"), cancelled.index("[wrapper]"))
            self._assert_cast_sequence(cancelled, ["chain-id", "estimate"])
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce)
            self.assertEqual(sandbox.native_balance(node_alias, account), initial_native_balance)

            rejected = shell.command(
                f"send {DESTINATION} 0.1 --yes",
                prompts=[(b"password:", wrong_password)],
            )
            self.assertNotIn(wrong_password, rejected)
            self.assertIn("[wrapper]", rejected)
            self.assertLess(rejected.lower().index("error"), rejected.index("[wrapper]"))
            self._assert_cast_sequence(rejected, ["chain-id", "estimate", "chain-id", "send"])
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce)
            self.assertEqual(sandbox.native_balance(node_alias, account), initial_native_balance)

            native_send = shell.command(
                f"send {DESTINATION} 0.1",
                prompts=[(b"Type 'yes' to continue:", "yes"), (b"password:", password)],
            )
            self.assertNotIn(password, native_send)
            self.assertLess(
                native_send.index("Transaction submitted"), native_send.index("[wrapper]")
            )
            self.assertIn("cast estimate", native_send)
            self.assertIn("cast send", native_send)
            self._assert_cast_sequence(native_send, ["chain-id", "estimate", "chain-id", "send"])
            native_hash = self._transaction_hash(native_send, "Transaction submitted")
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce + 1)
            self.assertEqual(sandbox.native_balance(node_alias, DESTINATION), 10**17)
            sender_balance_after_send = sandbox.native_balance(node_alias, account)
            self.assertLess(sender_balance_after_send, initial_native_balance - 10**17)

            inspected = shell.command(f"tx inspect {native_hash}")
            self.assertIn(native_hash, inspected)
            self.assertIn("RECEIPT", inspected)
            self.assertIn('"status": "0x1"', inspected)
            self._assert_cast_sequence(inspected, ["chain-id", "tx", "chain-id", "rpc"])

            token_dry_run = shell.command(f"token send {TOKEN} {DESTINATION} 1.25 --dry-run")
            self.assertIn("transaction preview", token_dry_run.lower())
            self.assertIn("1.25", token_dry_run)
            self._assert_cast_sequence(
                token_dry_run,
                ["chain-id", "call", "chain-id", "call", "chain-id", "estimate"],
            )
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce + 1)
            self.assertEqual(sandbox.token_balance(node_alias, account), TOKEN_INITIAL_BALANCE)

            false_transfer = shell.command(f"token send {FALSE_TOKEN} {DESTINATION} 1.25 --yes")
            self.assertIn("returned false", false_transfer)
            self.assertLess(
                false_transfer.index("returned false"), false_transfer.index("[wrapper]")
            )
            self._assert_cast_sequence(false_transfer, ["chain-id", "call", "chain-id", "call"])
            self.assertNotIn("cast estimate", false_transfer)
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce + 1)
            self.assertEqual(sandbox.token_balance(node_alias, account), TOKEN_INITIAL_BALANCE)

            token_send = shell.command(
                f"token send {TOKEN} {DESTINATION} 1.25 --yes",
                prompts=[(b"password:", password)],
            )
            self.assertNotIn(password, token_send)
            self.assertIn("Token transaction submitted", token_send)
            self.assertIn("cast estimate", token_send)
            self.assertIn("cast send", token_send)
            self._assert_cast_sequence(
                token_send,
                [
                    "chain-id",
                    "call",
                    "chain-id",
                    "call",
                    "chain-id",
                    "estimate",
                    "chain-id",
                    "send",
                ],
            )
            token_hash = self._transaction_hash(token_send, "Token transaction submitted")
            self.assertEqual(sandbox.transaction_count(node_alias, account), initial_nonce + 2)
            self.assertEqual(
                sandbox.token_balance(node_alias, account),
                TOKEN_INITIAL_BALANCE - 1_250_000_000_000_000_000,
            )
            self.assertEqual(
                sandbox.token_balance(node_alias, DESTINATION), 1_250_000_000_000_000_000
            )

            token_receipt = shell.command(f"tx inspect {token_hash}")
            self.assertIn('"status": "0x1"', token_receipt)
            self._assert_cast_sequence(token_receipt, ["chain-id", "tx", "chain-id", "rpc"])

            local_error = shell.command("not-a-wallet-command")
            self.assertIn("Unknown command", local_error)
            self.assertIn("No external command ran", local_error)

        # The actual launcher also handles one-shot JSON mode: result JSON stays on
        # stdout while all Cast commands and local-only traces stay on stderr.
        json_chain = self._run_one_shot(profile, environment, "chain info", json_output=True)
        self.assertEqual(json_chain.returncode, 0, json_chain.stderr)
        chain_data = json.loads(json_chain.stdout)
        self.assertTrue(chain_data["ok"])
        self.assertEqual(chain_data["chain_id"], chain_id)
        self.assertIn("No external command ran", json_chain.stderr)

        json_balance = self._run_one_shot(profile, environment, "balance", json_output=True)
        self.assertEqual(json_balance.returncode, 0, json_balance.stderr)
        balance_data = json.loads(json_balance.stdout)
        self.assertTrue(balance_data["ok"])
        self.assertEqual(balance_data["chain"], "mainnet")
        self.assertEqual(balance_data["address"].lower(), account.lower())
        self.assertGreater(int(balance_data["balance_base_units"]), 0)
        self.assertLess(int(balance_data["balance_base_units"]), 10**22)
        self.assertEqual(json_balance.stderr.count("[wrapper]"), 2)
        self.assertNotIn(environment[f"{profile.upper()}_WALLET_RPC_URL"], json_balance.stderr)

        json_error = self._run_one_shot(profile, environment, "bad-command", json_output=True)
        self.assertNotEqual(json_error.returncode, 0)
        self.assertEqual(json_error.stdout, "")
        error_data = _json_error(json_error.stderr)
        self.assertFalse(error_data["ok"])
        self.assertIn("No external command ran", json_error.stderr)

        return account

    def _run_one_shot(
        self,
        profile: str,
        environment: dict[str, str],
        command: str,
        *,
        json_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        launcher = ROOT / "scripts" / f"{profile}-wallet-cli"
        args = [str(launcher), "-c", command]
        if json_output:
            args.append("--json")
        return subprocess.run(
            args,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )

    def _assert_cast_sequence(self, output: str, expected_fragments: list[str]) -> None:
        actual = [
            line.removeprefix("[wrapper] ")
            for line in output.splitlines()
            if line.startswith("[wrapper] /usr/local/bin/cast ")
        ]
        self.assertEqual(len(actual), len(expected_fragments), output)
        for invocation, fragment in zip(actual, expected_fragments, strict=True):
            self.assertIn(f"cast {fragment}", invocation)
        self.assertIn("--rpc-url '<redacted-rpc-url>'", output)
        self.assertNotIn(":8545", output)

    def _transaction_hash(self, output: str, prefix: str) -> str:
        start = output.index(prefix)
        match = re.search(r"(0x[0-9a-fA-F]{64})", output[start:])
        self.assertIsNotNone(match, output)
        assert match is not None
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
