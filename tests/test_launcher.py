"""Tests for the Docker launcher, using a harmless fake Docker executable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "ethereum-wallet-cli"
MONAD_LAUNCHER = ROOT / "scripts" / "monad-wallet-cli"
BSC_LAUNCHER = ROOT / "scripts" / "bsc-wallet-cli"


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="evm-wallet-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker-calls.jsonl"
        docker = self.bin / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['DOCKER_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'pull':\n"
            "    sys.exit(int(os.environ.get('DOCKER_PULL_STATUS', '0')))\n"
            "print('fake docker completed')\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)

    def run_launcher(
        self,
        *args: str,
        launcher: Path = LAUNCHER,
        **extra_env: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": f"{self.bin}:{Path(sys.executable).parent}:/usr/bin:/bin",
            "HOME": str(self.root / "isolated-home"),
            "DOCKER_LOG": str(self.log),
        }
        environment.update(extra_env)
        return subprocess.run(
            [str(launcher), *args],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_local_image_creates_private_config_dir_and_passes_args_safely(self) -> None:
        config = self.root / "config dir with spaces"
        result = self.run_launcher(
            "--network",
            "testnet",
            "wallet",
            "list",
            ETHEREUM_WALLET_CONFIG_DIR=str(config),
            ETHEREUM_WALLET_IMAGE="ethereum-wallet-cli:local",
            ETHEREUM_WALLET_NETWORK="testnet",
            ETHEREUM_WALLET_RPC_URL="http://127.0.0.1:8545",
            PRIVATE_KEY="must-not-be-forwarded",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0:2], ["run", "--rm"])
        self.assertIn("ETHEREUM_WALLET_NETWORK", calls[0])
        self.assertIn("ETHEREUM_WALLET_RPC_URL", calls[0])
        self.assertNotIn("PRIVATE_KEY", calls[0])
        self.assertIn(f"type=bind,source={config},target=/data", calls[0])
        self.assertIn("-i", calls[0])
        self.assertNotIn("-it", calls[0])
        self.assertIn(f"{os.getuid()}:{os.getgid()}", calls[0])
        self.assertIn("--cap-drop", calls[0])
        self.assertIn("ALL", calls[0])
        self.assertIn("--security-opt", calls[0])
        self.assertIn("no-new-privileges", calls[0])
        self.assertIn("--read-only", calls[0])
        self.assertIn("/tmp:rw,nosuid,nodev,size=64m", calls[0])
        self.assertEqual(
            calls[0][-5:], ["ethereum-wallet-cli:local", "--network", "testnet", "wallet", "list"]
        )

    def test_remote_image_is_pulled_before_run(self) -> None:
        image = "registry.example.invalid/tools/ethereum-wallet-cli:2026.10"
        config = self.root / "cfg"
        result = self.run_launcher(
            "--help",
            ETHEREUM_WALLET_CONFIG_DIR=str(config),
            ETHEREUM_WALLET_IMAGE=image,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0], ["pull", image])
        self.assertEqual(calls[1][-2:], [image, "--help"])

    def test_failed_image_pull_does_not_start_container(self) -> None:
        image = "registry.example.invalid/tools/ethereum-wallet-cli:unavailable"
        result = self.run_launcher(
            "--help",
            ETHEREUM_WALLET_CONFIG_DIR=str(self.root / "cfg"),
            ETHEREUM_WALLET_IMAGE=image,
            DOCKER_PULL_STATUS="17",
        )

        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.calls(), [["pull", image]])

    def test_xdg_default_uses_isolated_config_root(self) -> None:
        xdg = self.root / "xdg data"
        result = self.run_launcher("--version", XDG_CONFIG_HOME=str(xdg))

        self.assertEqual(result.returncode, 0, result.stderr)
        config = xdg / "ethereum-wallet-cli"
        self.assertTrue(config.is_dir())
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.calls()[0], ["pull", "ghcr.io/vibe-wallets/ethereum-wallet-cli:main"])
        self.assertIn(f"type=bind,source={config},target=/data", self.calls()[1])

    def test_monad_launcher_uses_monad_entrypoint_config_and_environment_allowlist(self) -> None:
        config = self.root / "monad config"
        result = self.run_launcher(
            "-c",
            "chain list",
            launcher=MONAD_LAUNCHER,
            MONAD_WALLET_CONFIG_DIR=str(config),
            MONAD_WALLET_IMAGE="ethereum-wallet-cli:local",
            MONAD_WALLET_NETWORK="testnet",
            MONAD_WALLET_RPC_URL="https://monad-private.example.invalid/rpc",
            ETHEREUM_WALLET_CONFIG_DIR=str(self.root / "wrong-ethereum-config"),
            ETHEREUM_WALLET_NETWORK="testnet",
            ETHEREUM_WALLET_RPC_URL="https://ethereum-private.example.invalid/rpc",
            PRIVATE_KEY="must-not-be-forwarded",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertIn("--entrypoint", call)
        self.assertIn("monad-wallet-cli", call)
        self.assertIn("MONAD_WALLET_NETWORK", call)
        self.assertIn("MONAD_WALLET_RPC_URL", call)
        self.assertNotIn("ETHEREUM_WALLET_NETWORK", call)
        self.assertNotIn("ETHEREUM_WALLET_RPC_URL", call)
        self.assertNotIn("PRIVATE_KEY", call)
        self.assertIn(f"type=bind,source={config},target=/data", call)
        self.assertEqual(call[-3:], ["ethereum-wallet-cli:local", "-c", "chain list"])

    def test_monad_launcher_default_directory_is_separate_under_xdg(self) -> None:
        xdg = self.root / "xdg config"
        result = self.run_launcher("--version", launcher=MONAD_LAUNCHER, XDG_CONFIG_HOME=str(xdg))

        self.assertEqual(result.returncode, 0, result.stderr)
        config = xdg / "monad-wallet-cli"
        self.assertTrue(config.is_dir())
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.calls()[0], ["pull", "ghcr.io/vibe-wallets/ethereum-wallet-cli:main"])
        call = self.calls()[1]
        self.assertIn("--entrypoint", call)
        self.assertIn("monad-wallet-cli", call)
        self.assertIn(f"type=bind,source={config},target=/data", call)

    def test_bsc_launcher_uses_bsc_entrypoint_config_and_environment_allowlist(self) -> None:
        config = self.root / "bsc config"
        result = self.run_launcher(
            "-c",
            "chain list",
            launcher=BSC_LAUNCHER,
            BSC_WALLET_CONFIG_DIR=str(config),
            BSC_WALLET_IMAGE="ethereum-wallet-cli:local",
            BSC_WALLET_NETWORK="testnet",
            BSC_WALLET_RPC_URL="https://bsc-private.example.invalid/rpc",
            MONAD_WALLET_CONFIG_DIR=str(self.root / "wrong-monad-config"),
            MONAD_WALLET_NETWORK="testnet",
            MONAD_WALLET_RPC_URL="https://monad-private.example.invalid/rpc",
            PRIVATE_KEY="must-not-be-forwarded",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertIn("--entrypoint", call)
        self.assertIn("bsc-wallet-cli", call)
        self.assertIn("BSC_WALLET_NETWORK", call)
        self.assertIn("BSC_WALLET_RPC_URL", call)
        self.assertNotIn("MONAD_WALLET_NETWORK", call)
        self.assertNotIn("MONAD_WALLET_RPC_URL", call)
        self.assertNotIn("PRIVATE_KEY", call)
        self.assertIn(f"type=bind,source={config},target=/data", call)
        self.assertEqual(call[-3:], ["ethereum-wallet-cli:local", "-c", "chain list"])

    def test_bsc_launcher_default_directory_is_separate_under_xdg(self) -> None:
        xdg = self.root / "xdg bsc"
        result = self.run_launcher("--version", launcher=BSC_LAUNCHER, XDG_CONFIG_HOME=str(xdg))

        self.assertEqual(result.returncode, 0, result.stderr)
        config = xdg / "bsc-wallet-cli"
        self.assertTrue(config.is_dir())
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.calls()[0], ["pull", "ghcr.io/vibe-wallets/ethereum-wallet-cli:main"])
        call = self.calls()[1]
        self.assertIn("--entrypoint", call)
        self.assertIn("bsc-wallet-cli", call)
        self.assertIn(f"type=bind,source={config},target=/data", call)

    def test_named_docker_network_is_profile_specific_and_not_forwarded_as_wallet_env(self):
        result = self.run_launcher(
            "--version",
            launcher=MONAD_LAUNCHER,
            MONAD_WALLET_IMAGE="ethereum-wallet-cli:local",
            MONAD_WALLET_DOCKER_NETWORK="isolated-monad-test",
            ETHEREUM_WALLET_DOCKER_NETWORK="wrong-network",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.calls()[0]
        self.assertEqual(call[call.index("--network") + 1], "isolated-monad-test")
        self.assertNotIn("wrong-network", call)
        self.assertNotIn("MONAD_WALLET_DOCKER_NETWORK", call)

    def test_failed_default_registry_pull_does_not_start_or_build_an_image(self):
        result = self.run_launcher("--version", DOCKER_PULL_STATUS="19")
        self.assertEqual(result.returncode, 19)
        self.assertEqual(self.calls(), [["pull", "ghcr.io/vibe-wallets/ethereum-wallet-cli:main"]])


if __name__ == "__main__":
    unittest.main()
