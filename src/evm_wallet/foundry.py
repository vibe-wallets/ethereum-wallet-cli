"""A narrow, shell-free subprocess adapter around Foundry's ``cast``."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .chains import Chain
from .errors import FoundryError

INTEGER_RE = re.compile(r"^(?:0x[0-9a-fA-F]+|[0-9]+)$")


def parse_integer_output(value: str, label: str) -> int:
    """Parse a decimal or 0x-prefixed unsigned integer or raise an error."""
    text = value.strip()
    if not INTEGER_RE.fullmatch(text):
        raise FoundryError(f"Foundry returned an invalid {label} value.")
    return int(text, 16 if text.startswith("0x") else 10)


def unwrap_cast_json(value: str) -> Any:
    """Unwrap Cast's versioned JSON envelope while accepting raw JSON results."""
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise FoundryError("Foundry returned invalid JSON output.") from exc
    if isinstance(result, dict) and result.get("success") is False and "errors" in result:
        errors = result.get("errors")
        message = (
            "; ".join(str(item) for item in errors)
            if isinstance(errors, list)
            else "Cast command failed"
        )
        raise FoundryError(message or "Cast command failed.")
    if isinstance(result, dict) and result.get("success") is True and "data" in result:
        return result["data"]
    return result


class CastClient:
    """A narrow, shell-free subprocess adapter around Foundry's `cast`."""

    def __init__(
        self,
        config_dir: str | os.PathLike[str],
        executable: str = "cast",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.config_dir = Path(config_dir).expanduser().absolute()
        self.executable = shutil.which(executable) or executable
        self.runner = runner
        self.last_stderr = ""
        self.trace: list[str] = []

    def clear_trace(self) -> None:
        self.trace.clear()

    def flush_trace(self) -> None:
        sys.stdout.flush()
        if self.trace:
            for command in self.trace:
                print(f"[wrapper] {command}", file=sys.stderr)
        else:
            print("[wrapper] No external command ran (local command).", file=sys.stderr)
        self.clear_trace()

    def _environment(self) -> dict[str, str]:
        source = os.environ
        env: dict[str, str] = {"HOME": str(self.config_dir), "FOUNDRY_CONFIG": "/dev/null"}
        for key in ("PATH", "TERM", "LANG", "LC_ALL", "NO_COLOR", "SSL_CERT_FILE", "SSL_CERT_DIR"):
            if source.get(key):
                env[key] = source[key]
        return env

    def run(self, args: list[str], *, interactive: bool = False) -> str:
        """Run one Cast command and return its trimmed stdout.

        The trace records a redacted form of every invocation. A non-zero exit
        becomes a :class:`FoundryError` with a bounded, URL-redacted detail.
        """
        command = [self.executable, *args]
        self.trace.append(self._display_command(command))
        try:
            options: dict[str, Any] = {
                "stdin": None,
                "stdout": subprocess.PIPE,
                # Prompts/errors may contain the provider URL. Interactive prompts
                # are announced by our CLI before launch; capture and redact stderr.
                "stderr": subprocess.PIPE,
            }
            result = self.runner(
                command,
                cwd=self.config_dir,
                env=self._environment(),
                text=True,
                check=False,
                **options,
            )
        except FileNotFoundError as exc:
            raise FoundryError(
                "Foundry Cast was not found. Install Foundry and make sure 'cast' is on PATH."
            ) from exc
        except OSError as exc:
            raise FoundryError(
                f"Could not start Foundry Cast: {exc.strerror or 'process launch failed'}."
            ) from exc
        stdout = result.stdout or ""
        self.last_stderr = result.stderr or ""
        if result.returncode != 0:
            stderr = result.stderr or ""
            detail = stderr.strip() or stdout.strip()
            try:
                rpc_index = args.index("--rpc-url")
                rpc_url = args[rpc_index + 1]
                if rpc_url:
                    detail = detail.replace(rpc_url, "<rpc-url>")
            except (ValueError, IndexError):
                pass
            if len(detail) > 500:
                detail = detail[:497] + "..."
            raise FoundryError(
                f"Foundry Cast exited with status {result.returncode}."
                + (f" {detail}" if detail else "")
            )
        output = stdout.strip()
        try:
            rpc_index = args.index("--rpc-url")
            rpc_url = args[rpc_index + 1]
            if rpc_url:
                output = output.replace(rpc_url, "<rpc-url>")
        except (ValueError, IndexError):
            pass
        return output

    @staticmethod
    def _display_command(command: list[str]) -> str:
        public_urls = {
            "https://ethereum-rpc.publicnode.com",
            "https://ethereum-sepolia-rpc.publicnode.com",
            "https://rpc.monad.xyz",
            "https://testnet-rpc.monad.xyz",
            "https://bsc-rpc.publicnode.com",
            "https://bsc-testnet-rpc.publicnode.com",
        }
        shown = list(command)
        for index, value in enumerate(shown[:-1]):
            if value == "--rpc-url" and shown[index + 1] not in public_urls:
                shown[index + 1] = "<redacted-rpc-url>"
        return shlex.join(shown)

    def verify_chain(self, chain: Chain) -> None:
        """Refuse to continue when the endpoint reports a different chain ID."""
        output = self.run(["chain-id", "--rpc-url", chain.rpc_url])
        actual = parse_integer_output(output, "chain ID")
        if actual != chain.chain_id:
            raise FoundryError(
                f"RPC endpoint reported chain ID {actual}, but '{chain.name}' is configured "
                f"for {chain.chain_id}; refusing to continue."
            )

    def network(
        self,
        chain: Chain,
        args: list[str],
        *,
        json_output: bool = False,
        interactive: bool = False,
        verify: bool = True,
    ) -> str:
        """Verify the chain, then run a command against its RPC endpoint."""
        if verify:
            self.verify_chain(chain)
        command = [*args, "--rpc-url", chain.rpc_url]
        if json_output:
            command.append("--json")
        return self.run(command, interactive=interactive)

    def rpc(self, chain: Chain, method: str, *params: str, verify: bool = True) -> str:
        return self.network(chain, ["rpc", method, *params], verify=verify)

    def rpc_integer(self, chain: Chain, method: str, *params: str, label: str) -> int:
        """Call an RPC method and parse its unsigned integer result."""
        return parse_rpc_integer(self.rpc(chain, method, *params), label)

    def call_uint(self, chain: Chain, contract: str, signature: str, *args: str) -> int:
        """Call a read-only contract function and parse its uint256 result."""
        output = self.network(chain, ["call", contract, signature, *args], json_output=True)
        return parse_rpc_integer(output, "contract call")

    def call_raw(self, chain: Chain, contract: str, signature: str, *args: str) -> str:
        """Call a read-only contract function and return its raw output."""
        return self.network(chain, ["call", contract, signature, *args])

    def estimate(self, chain: Chain, args: list[str]) -> str:
        """Estimate gas for a transaction without signing it."""
        return self.network(chain, ["estimate", *args])

    def send(self, chain: Chain, args: list[str]) -> str:
        """Sign and broadcast a transaction through Cast's encrypted keystore."""
        # Cast prompts on the controlling terminal to unlock the encrypted keystore.
        return self.network(
            chain,
            ["send", *args, "--chain", str(chain.chain_id)],
            json_output=True,
            interactive=True,
        )


def parse_rpc_integer(output: str, label: str) -> int:
    """Accept the numeric shapes Cast returns for RPC reads and parse one uint256."""
    text = output.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = text
    if isinstance(value, dict) and value.get("success") is True and "data" in value:
        value = value["data"]
    if isinstance(value, dict) and value.get("success") is False and "errors" in value:
        errors = value.get("errors")
        message = (
            "; ".join(str(item) for item in errors)
            if isinstance(errors, list)
            else "Cast command failed"
        )
        raise FoundryError(message or "Cast command failed.")
    if isinstance(value, list):
        if len(value) != 1:
            raise FoundryError(f"Foundry returned an invalid {label} value.")
        value = value[0]
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value < (1 << 256):
            return value
        raise FoundryError(f"Foundry returned an invalid {label} value.")
    if isinstance(value, str):
        candidate = value.strip().split()[0] if value.strip() else ""
        try:
            parsed = parse_integer_output(candidate, label)
            if parsed < (1 << 256):
                return parsed
        except FoundryError:
            pass
    raise FoundryError(f"Foundry returned an invalid {label} value.")
