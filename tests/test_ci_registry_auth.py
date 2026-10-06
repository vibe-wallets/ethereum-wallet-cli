"""CI authentication must not leak tokens or replace existing Docker state."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "registry_auth.py"


class RegistryAuthTests(unittest.TestCase):
    def test_creates_restricted_explicit_config_without_token_output(self):
        with tempfile.TemporaryDirectory(prefix="wallet-ci-auth-") as temporary:
            directory = Path(temporary) / "ci-docker"
            environment = os.environ.copy()
            environment.update(REGISTRY_USER="test-user", REGISTRY_TOKEN="test-only-token")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--config-dir", str(directory)],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            path = directory / "config.json"
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            encoded = json.loads(path.read_text())["auths"]["ghcr.io"]["auth"]
            self.assertEqual(base64.b64decode(encoded).decode(), "test-user:test-only-token")
            repeated = subprocess.run(
                [sys.executable, str(SCRIPT), "--config-dir", str(directory)],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(json.loads(path.read_text())["auths"]["ghcr.io"]["auth"], encoded)
            self.assertNotIn("test-only-token", repeated.stderr)

    def test_missing_job_credentials_writes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="wallet-ci-auth-") as temporary:
            directory = Path(temporary) / "ci-docker"
            environment = os.environ.copy()
            environment.pop("REGISTRY_USER", None)
            environment.pop("REGISTRY_TOKEN", None)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--config-dir", str(directory)],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(directory.exists())
