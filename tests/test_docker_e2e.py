"""Opt-in PTY checks of both real Docker launchers, with disposable wallets."""

from __future__ import annotations

import json
import os
import pty
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENABLED = os.environ.get("WALLET_CLI_DOCKER_E2E") == "1" and shutil.which("docker")


@unittest.skipUnless(ENABLED, "set WALLET_CLI_DOCKER_E2E=1 with a built image and Docker")
class DockerLauncherTests(unittest.TestCase):
    def test_both_launchers_hide_secrets_trace_after_results_and_isolate_wallets(self):
        with tempfile.TemporaryDirectory(prefix="evm-docker-e2e-") as temporary:
            folders = {profile: Path(temporary) / profile for profile in ("ethereum", "monad")}
            environment = os.environ.copy()
            for name in list(environment):
                if name.startswith(("ETHEREUM_WALLET_", "MONAD_WALLET_")):
                    environment.pop(name)
            environment.update(
                ETHEREUM_WALLET_CONFIG_DIR=str(folders["ethereum"]),
                MONAD_WALLET_CONFIG_DIR=str(folders["monad"]),
            )
            image = os.environ.get("WALLET_CLI_DOCKER_E2E_IMAGE", "ethereum-wallet-cli:local")
            environment.update(ETHEREUM_WALLET_IMAGE=image, MONAD_WALLET_IMAGE=image)
            addresses = []
            for profile, expected_chain in (("ethereum", 1), ("monad", 143)):
                launcher = ROOT / "scripts" / f"{profile}-wallet-cli"
                password = f"temporary-{profile}-e2e-passphrase"
                code, output = self.run_terminal(
                    [str(launcher), "-c", "wallet new smoke"], environment, password
                )
                self.assertEqual(code, 0, output)
                self.assertNotIn(password, output)
                self.assertIn("[wrapper] /usr/local/bin/cast wallet new", output)
                self.assertLess(output.index("Wallet 'smoke' is ready"), output.index("[wrapper]"))
                state = json.loads((folders[profile] / "config.json").read_text())
                self.assertEqual(set(state["wallets"]), {"smoke"})
                wallet = state["wallets"]["smoke"]
                addresses.append(wallet["address"])
                path = folders[profile] / wallet["keystore"]
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIsInstance(json.loads(path.read_text())["crypto"], dict)
                result = subprocess.run(
                    [str(launcher), "-c", "chain info", "--json"],
                    env=environment,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["chain_id"], expected_chain)
                self.assertIn("No external command ran", result.stderr)
            self.assertNotEqual(addresses[0], addresses[1])

    @staticmethod
    def run_terminal(argv, environment, password):
        pid, terminal = pty.fork()
        if pid == 0:
            os.execve(argv[0], argv, environment)
        output = bytearray()
        sent = False
        reaped = False
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                ready, _, _ = select.select([terminal], [], [], 0.2)
                if not ready:
                    continue
                try:
                    chunk = os.read(terminal, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                if b"Enter secret:" in output and not sent:
                    # Wait until Foundry has disabled terminal echo after its prompt.
                    time.sleep(0.1)
                    os.write(terminal, password.encode() + b"\n")
                    sent = True
            else:
                raise AssertionError("Docker wallet prompt timed out")
            _, status = os.waitpid(pid, 0)
            reaped = True
            return os.waitstatus_to_exitcode(status), output.decode(errors="replace")
        finally:
            if not reaped:
                try:
                    os.kill(pid, signal.SIGTERM)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass
            os.close(terminal)
