from __future__ import annotations

import json
import os
import re
import stat
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, TextIO

from .amounts import format_units, to_base_units, validate_address, validate_tx_hash
from .chains import (
    BUILTIN_CHAINS,
    PROFILE_NETWORKS,
    Chain,
    chain_from_config,
    validate_rpc_url,
)
from .config import ConfigStore, validate_alias
from .errors import ConfigurationError, FoundryError, WalletCliError
from .foundry import CastClient, unwrap_cast_json

KEYSTORE_ADDRESS_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class Application:
    """Command services and their small injectable boundaries for tests."""

    def __init__(
        self,
        config_dir: str | os.PathLike[str] | None = None,
        *,
        cast_executable: str = "cast",
        runner: Callable[..., Any] | None = None,
        input_fn: Callable[[str], str] = input,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        default_chain: str = "ethereum",
        chain_name: str | None = None,
        rpc_url: str | None = None,
        profile: str = "ethereum",
        network_name: str = "mainnet",
    ):
        self.store = ConfigStore(config_dir)
        self.store.ensure_directory()
        kwargs: dict[str, Any] = {}
        if runner is not None:
            kwargs["runner"] = runner
        self.cast = CastClient(self.store.directory, executable=cast_executable, **kwargs)
        self.input_fn = input_fn
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.profile = profile
        self.network_name = network_name
        profile_networks = PROFILE_NETWORKS.get(profile, {})
        self.startup_chain = chain_name or profile_networks.get(network_name) or default_chain
        self.rpc_url_override = validate_rpc_url(rpc_url) if rpc_url else None
        self.session_wallet_alias: str | None = None

    def config(self) -> dict[str, Any]:
        return self.store.load()

    def active_chain(self, state: dict[str, Any] | None = None) -> Chain:
        state = state or self.config()
        name = self.startup_chain
        if name in BUILTIN_CHAINS:
            expected = BUILTIN_CHAINS[name]
            configured = state["chains"].get(name)
            if not isinstance(configured, dict) or configured.get("chain_id") != expected.chain_id:
                raise WalletCliError(
                    f"Configured chain ID for '{name}' does not match its built-in network ID."
                )
            chain = expected
        elif name in state["chains"]:
            chain = chain_from_config(name, state["chains"][name])
        else:
            raise WalletCliError(
                f"Network '{name}' is not configured for the {self.profile} profile."
            )
        return replace(chain, rpc_url=self.rpc_url_override) if self.rpc_url_override else chain

    def network_label(self, chain: Chain) -> str:
        for label, configured_name in PROFILE_NETWORKS.get(self.profile, {}).items():
            if configured_name == chain.name:
                return label
        return chain.name

    def active_wallet_alias(self, state: dict[str, Any] | None = None) -> str | None:
        state = state or self.config()
        return self.session_wallet_alias or state.get("default_wallet")

    def wallet(
        self, alias: str | None = None, state: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any], Path]:
        state = state or self.config()
        selected = alias or self.active_wallet_alias(state)
        if not selected:
            raise WalletCliError(
                "No wallet is selected. Create or import one with 'wallet new' or 'wallet import'."
            )
        if selected not in state["wallets"]:
            raise WalletCliError(f"Wallet alias '{selected}' was not found.")
        metadata = state["wallets"][selected]
        keystore = self.store.keystore_path(metadata)
        self.validate_keystore_file(keystore, expected_address=metadata["address"])
        return selected, metadata, keystore

    def require_terminal(self, action: str) -> None:
        if not self.stdin.isatty() or not self.stdout.isatty():
            raise WalletCliError(
                f"'{action}' requires an interactive terminal for Foundry's hidden keystore prompt."
            )

    @staticmethod
    def validate_keystore_file(path: Path, *, expected_address: str | None = None) -> str:
        if path.is_symlink():
            raise ConfigurationError("Wallet keystore cannot be a symlink.")
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ConfigurationError("Wallet keystore must be a regular file.")
            os.chmod(path, 0o600)
            with path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except ConfigurationError:
            raise
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise ConfigurationError(
                "Foundry did not create a readable encrypted wallet keystore."
            ) from exc
        crypto = (
            document.get("crypto", document.get("Crypto")) if isinstance(document, dict) else None
        )
        if not isinstance(crypto, dict):
            raise ConfigurationError("Foundry keystore is missing its encrypted Crypto object.")
        address = document.get("address")
        if address is not None:
            if isinstance(address, str) and address.startswith("0x"):
                address = address[2:]
            if not isinstance(address, str) or not KEYSTORE_ADDRESS_RE.fullmatch(address):
                raise ConfigurationError("Foundry keystore contains an invalid address.")
            normalized = "0x" + address.lower()
        elif expected_address is not None:
            normalized = expected_address.lower()
        else:
            raise ConfigurationError(
                "Foundry did not return the address for its encrypted keystore."
            )
        if expected_address is not None and normalized.lower() != expected_address.lower():
            raise ConfigurationError(
                "Wallet metadata address does not match its encrypted keystore."
            )
        return normalized

    def create_wallet(self, alias: str, kind: str) -> dict[str, Any]:
        validate_alias(alias)
        self.require_terminal(f"wallet {kind}")
        state = self.config()
        if alias in state["wallets"]:
            raise WalletCliError(f"Wallet alias '{alias}' already exists; choose another alias.")
        self.store.ensure_directory(wallets=True)
        name = self.store.allocate_keystore_name()
        keystore_path = self.store.wallet_dir / name
        if keystore_path.exists() or keystore_path.is_symlink():
            raise ConfigurationError(
                "A generated wallet keystore path already exists; retry the command."
            )
        if kind == "new":
            cast_args = ["wallet", "new", str(self.store.wallet_dir), name]
            sys.stderr.write(
                "Foundry will prompt you to set a keystore passphrase; input is hidden.\n"
            )
        elif kind == "import":
            cast_args = [
                "wallet",
                "import",
                name,
                "--keystore-dir",
                str(self.store.wallet_dir),
                "--interactive",
            ]
            sys.stderr.write(
                "Foundry will prompt for the private key and a keystore passphrase; input is hidden.\n"
            )
        else:
            raise WalletCliError("Wallet operation must be 'new' or 'import'.")
        cast_output = self.cast.run(cast_args, interactive=True)
        if not keystore_path.exists() or keystore_path.is_symlink():
            raise ConfigurationError(
                "Foundry reported success but did not create the requested keystore file."
            )
        address_matches = re.findall(
            r"(?i)\bAddress:\s*(0x[0-9a-f]{40})", f"{cast_output}\n{self.cast.last_stderr}"
        )
        if not address_matches:
            address_matches = re.findall(
                r"(?i)(?<![0-9a-f])0x[0-9a-f]{40}(?![0-9a-f])", cast_output
            )
        if not address_matches:
            raise ConfigurationError(
                "Foundry created the encrypted keystore but did not report its address."
            )
        address = self.validate_keystore_file(keystore_path, expected_address=address_matches[-1])
        relative = f"wallets/{name}"

        def add_wallet(config: dict[str, Any]) -> None:
            if alias in config["wallets"]:
                raise WalletCliError(
                    f"Wallet alias '{alias}' already exists; the new keystore was preserved as an unregistered file."
                )
            config["wallets"][alias] = {"keystore": relative, "address": address}
            if config["default_wallet"] is None:
                config["default_wallet"] = alias

        self.store.update(add_wallet)
        self.session_wallet_alias = alias
        return {
            "command": f"wallet {kind}",
            "alias": alias,
            "address": address,
            "keystore": relative,
        }

    def json_rpc_integer(self, chain: Chain, method: str, *params: str, label: str) -> int:
        return self.cast.rpc_integer(chain, method, *params, label=label)

    @staticmethod
    def _parse_json_result(output: str, label: str) -> Any:
        try:
            return unwrap_cast_json(output)
        except FoundryError as exc:
            raise FoundryError(f"Foundry returned an invalid {label} response.") from exc

    def contract_uint(self, chain: Chain, contract: str, signature: str, *arguments: str) -> int:
        return self.cast.call_uint(chain, contract, signature, *arguments)

    def simulate_erc20_transfer(
        self, chain: Chain, contract: str, sender: str, destination: str, amount: int
    ) -> None:
        output = self.cast.call_raw(
            chain,
            contract,
            "transfer(address,uint256)",
            destination,
            str(amount),
            "--from",
            sender,
        )
        text = output.strip()
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = text
        if isinstance(decoded, dict) and decoded.get("success") is True:
            decoded = decoded.get("data")
        if isinstance(decoded, bool):
            if not decoded:
                raise WalletCliError("Token transfer simulation returned false; refusing to sign.")
            return
        if not isinstance(decoded, str):
            raise FoundryError("Foundry returned an invalid token transfer simulation result.")
        data = decoded.strip()
        if data in {"", "0x", "0X"}:
            # Some older ERC20 tokens omit the optional boolean return value.
            return
        if data.lower().startswith("0x"):
            data = data[2:]
        if not data or not re.fullmatch(r"[0-9a-fA-F]+", data):
            raise FoundryError("Foundry returned an invalid token transfer simulation result.")
        result = int(data, 16)
        if result == 0:
            raise WalletCliError("Token transfer simulation returned false; refusing to sign.")
        if result != 1:
            raise FoundryError("Token transfer simulation returned an invalid boolean value.")


def execute(command: list[str], app: Application, *, json_output: bool = False) -> dict[str, Any]:
    """Run one parsed command and return a JSON-serializable result mapping."""
    tokens = [token for token in command if token != "--json"]
    json_output = json_output or len(tokens) != len(command)
    del json_output  # Rendering is owned by cli.main; execution is format-independent.
    if not tokens:
        raise WalletCliError("Enter a command. Use 'help' to see the command list.")
    if tokens[0] in {"help", "--help", "-h"}:
        return {"command": "help", "text": HELP_TEXT}
    if tokens[0] in {"exit", "quit"}:
        return {"command": "exit"}

    if tokens[0] == "wallet":
        if len(tokens) < 2:
            raise WalletCliError(
                "Usage: wallet new|import ALIAS, wallet list|use|default|info [ALIAS]."
            )
        action = tokens[1]
        if action in {"new", "import"}:
            if len(tokens) != 3:
                raise WalletCliError(f"Usage: wallet {action} ALIAS.")
            return app.create_wallet(tokens[2], action)
        state = app.config()
        if action == "list" and len(tokens) == 2:
            wallets = []
            for alias, metadata in sorted(state["wallets"].items()):
                wallets.append(
                    {
                        "alias": alias,
                        "address": metadata["address"],
                        "current": alias == app.active_wallet_alias(state),
                        "default": alias == state["default_wallet"],
                    }
                )
            return {"command": "wallet list", "wallets": wallets}
        if action in {"use", "default"}:
            if len(tokens) != 3:
                raise WalletCliError(f"Usage: wallet {action} ALIAS.")
            alias = validate_alias(tokens[2])

            def select(config: dict[str, Any]) -> None:
                if alias not in config["wallets"]:
                    raise WalletCliError(f"Wallet alias '{alias}' was not found.")
                config["default_wallet"] = alias

            if action == "use":
                if alias not in state["wallets"]:
                    raise WalletCliError(f"Wallet alias '{alias}' was not found.")
                app.session_wallet_alias = alias
                return {
                    "command": "wallet use",
                    "alias": alias,
                    "address": state["wallets"][alias]["address"],
                }
            updated = app.store.update(select)
            app.session_wallet_alias = alias
            return {
                "command": "wallet default",
                "alias": alias,
                "address": updated["wallets"][alias]["address"],
            }
        if action == "info" and len(tokens) in {2, 3}:
            alias, metadata, keystore = app.wallet(tokens[2] if len(tokens) == 3 else None, state)
            return {
                "command": "wallet info",
                "alias": alias,
                "address": metadata["address"],
                "keystore": str(keystore),
            }
        raise WalletCliError(
            "Usage: wallet new|import ALIAS, wallet list|use|default|info [ALIAS]."
        )

    if tokens[0] == "address" and len(tokens) in {1, 2}:
        alias, metadata, _ = app.wallet(tokens[1] if len(tokens) == 2 else None)
        return {"command": "address", "alias": alias, "address": metadata["address"]}

    if tokens[0] == "chain":
        if len(tokens) < 2:
            raise WalletCliError("Usage: chain list | chain info [mainnet|testnet|local].")
        action = tokens[1]
        state = app.config()
        if action == "list" and len(tokens) == 2:
            current = app.network_name
            chains = []
            for network, name in PROFILE_NETWORKS.get(app.profile, {}).items():
                chain = app.active_chain(state) if network == current else BUILTIN_CHAINS[name]
                if network == current and app.rpc_url_override:
                    chain = replace(chain, rpc_url=app.rpc_url_override)
                chains.append(
                    {
                        "name": network,
                        "chain_id": chain.chain_id,
                        "rpc_url": chain.rpc_url,
                        "current": network == current,
                    }
                )
            return {"command": "chain list", "chains": chains}
        if action == "info" and len(tokens) in {2, 3}:
            network = tokens[2] if len(tokens) == 3 else app.network_name
            profile_networks = PROFILE_NETWORKS.get(app.profile, {})
            if network not in profile_networks:
                raise WalletCliError(
                    f"Network '{network}' is not available in the {app.profile} CLI."
                )
            chain_name = profile_networks[network]
            chain = (
                app.active_chain(state)
                if network == app.network_name
                else BUILTIN_CHAINS[chain_name]
            )
            if network == app.network_name and app.rpc_url_override:
                chain = replace(chain, rpc_url=app.rpc_url_override)
            return {
                "command": "chain info",
                "name": network,
                "chain_id": chain.chain_id,
                "rpc_url": chain.rpc_url,
                "current": network == app.network_name,
            }
        raise WalletCliError("Usage: chain list | chain info [mainnet|testnet|local].")

    if tokens[0] == "balance" and len(tokens) in {1, 2}:
        state = app.config()
        chain = app.active_chain(state)
        address = (
            validate_address(tokens[1], "address")
            if len(tokens) == 2
            else app.wallet(state=state)[1]["address"]
        )
        raw = app.json_rpc_integer(
            chain, "eth_getBalance", address, "latest", label="native balance"
        )
        return {
            "command": "balance",
            "chain": app.network_label(chain),
            "address": address,
            "balance_base_units": str(raw),
            "balance_native": format_units(raw, 18),
        }

    if tokens[0] == "send":
        dry_run = "--dry-run" in tokens
        yes = "--yes" in tokens
        args = [token for token in tokens[1:] if token not in {"--dry-run", "--yes"}]
        if len(args) != 2 or dry_run and yes:
            raise WalletCliError("Usage: send DESTINATION AMOUNT [--dry-run | --yes].")
        destination = validate_address(args[0], "destination")
        raw_amount = to_base_units(args[1], 18)
        state = app.config()
        chain = app.active_chain(state)
        alias, metadata, keystore = app.wallet(state=state)
        amount = format_units(raw_amount, 18)
        if not dry_run:
            app.require_terminal("send")
        gas = app.cast.estimate(
            chain, [destination, "--from", metadata["address"], "--value", f"{raw_amount}wei"]
        )
        if dry_run:
            return {
                "command": "send",
                "dry_run": True,
                "chain": app.network_label(chain),
                "chain_id": chain.chain_id,
                "from_wallet": alias,
                "from": metadata["address"],
                "to": destination,
                "amount": amount,
                "amount_base_units": str(raw_amount),
                "estimated_gas": gas,
            }
        if not yes:
            answer = app.input_fn(
                f"Send {amount} native units on {app.network_label(chain)} (chain ID {chain.chain_id})?\n"
                f"  from {alias} ({metadata['address']})\n  to   {destination}\n  estimated gas {gas}\n"
                "Type 'yes' to continue: "
            )
            if answer.strip().lower() != "yes":
                raise WalletCliError("Transaction cancelled.")
        sys.stderr.write(
            "Foundry will prompt for the selected keystore passphrase; input is hidden.\n"
        )
        output = app.cast.send(
            chain,
            [
                destination,
                "--from",
                metadata["address"],
                "--value",
                f"{raw_amount}wei",
                "--keystore",
                str(keystore),
            ],
        )
        tx_result, tx_hash, receipt_status = _parse_send_receipt(app, output, "native")
        if receipt_status == 0:
            raise WalletCliError(
                f"Transaction was mined with a failed status; transaction hash: {tx_hash}."
            )
        return {
            "command": "send",
            "dry_run": False,
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "wallet": alias,
            "from": metadata["address"],
            "to": destination,
            "amount": amount,
            "amount_base_units": str(raw_amount),
            "estimated_gas": gas,
            "transaction": tx_result,
            "transaction_hash": tx_hash,
        }

    if tokens[0] == "token" and len(tokens) >= 3:
        action = tokens[1]
        if action == "balance" and len(tokens) in {3, 4}:
            contract = validate_address(tokens[2], "token contract")
            state = app.config()
            chain = app.active_chain(state)
            owner = (
                validate_address(tokens[3], "owner address")
                if len(tokens) == 4
                else app.wallet(state=state)[1]["address"]
            )
            decimals = app.contract_uint(chain, contract, "decimals()(uint8)")
            if decimals > 255:
                raise WalletCliError("Token contract returned an invalid decimals value.")
            raw = app.contract_uint(chain, contract, "balanceOf(address)(uint256)", owner)
            return {
                "command": "token balance",
                "chain": app.network_label(chain),
                "contract": contract,
                "address": owner,
                "decimals": decimals,
                "balance_raw": str(raw),
                "balance": format_units(raw, decimals),
            }
        if action == "send":
            dry_run = "--dry-run" in tokens
            yes = "--yes" in tokens
            args = [token for token in tokens[2:] if token not in {"--dry-run", "--yes"}]
            if len(args) != 3 or dry_run and yes:
                raise WalletCliError(
                    "Usage: token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]."
                )
            contract = validate_address(args[0], "token contract")
            destination = validate_address(args[1], "destination")
            state = app.config()
            chain = app.active_chain(state)
            alias, metadata, keystore = app.wallet(state=state)
            if not dry_run:
                app.require_terminal("token send")
            decimals = app.contract_uint(chain, contract, "decimals()(uint8)")
            if decimals > 255:
                raise WalletCliError("Token contract returned an invalid decimals value.")
            raw_amount = to_base_units(args[2], decimals)
            amount = format_units(raw_amount, decimals)
            signature = "transfer(address,uint256)"
            app.simulate_erc20_transfer(
                chain, contract, metadata["address"], destination, raw_amount
            )
            gas = app.cast.estimate(
                chain,
                [contract, signature, destination, str(raw_amount), "--from", metadata["address"]],
            )
            if dry_run:
                return {
                    "command": "token send",
                    "dry_run": True,
                    "chain": app.network_label(chain),
                    "chain_id": chain.chain_id,
                    "contract": contract,
                    "from_wallet": alias,
                    "from": metadata["address"],
                    "to": destination,
                    "amount": amount,
                    "amount_raw": str(raw_amount),
                    "decimals": decimals,
                    "estimated_gas": gas,
                }
            if not yes:
                answer = app.input_fn(
                    f"Send {amount} token units on {app.network_label(chain)} (chain ID {chain.chain_id})?\n"
                    f"  wallet   {alias} ({metadata['address']})\n  contract {contract}\n"
                    f"  to       {destination}\n  estimated gas {gas}\nType 'yes' to continue: "
                )
                if answer.strip().lower() != "yes":
                    raise WalletCliError("Transaction cancelled.")
            sys.stderr.write(
                "Foundry will prompt for the selected keystore passphrase; input is hidden.\n"
            )
            output = app.cast.send(
                chain,
                [
                    contract,
                    signature,
                    destination,
                    str(raw_amount),
                    "--from",
                    metadata["address"],
                    "--keystore",
                    str(keystore),
                ],
            )
            tx_result, tx_hash, receipt_status = _parse_send_receipt(app, output, "token")
            if receipt_status == 0:
                raise WalletCliError(
                    f"Token transaction was mined with a failed status; transaction hash: {tx_hash}."
                )
            return {
                "command": "token send",
                "dry_run": False,
                "chain": app.network_label(chain),
                "chain_id": chain.chain_id,
                "contract": contract,
                "wallet": alias,
                "from": metadata["address"],
                "to": destination,
                "amount": amount,
                "amount_raw": str(raw_amount),
                "decimals": decimals,
                "estimated_gas": gas,
                "transaction": tx_result,
                "transaction_hash": tx_hash,
            }
        raise WalletCliError(
            "Usage: token balance CONTRACT [ADDRESS] | token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]."
        )

    if tokens[0] == "tx" and len(tokens) == 3 and tokens[1] == "inspect":
        tx_hash = validate_tx_hash(tokens[2])
        chain = app.active_chain()
        transaction_output = app.cast.network(chain, ["tx", tx_hash], json_output=True)
        receipt_output = app.cast.rpc(chain, "eth_getTransactionReceipt", tx_hash)
        transaction = app._parse_json_result(transaction_output, "transaction")
        try:
            receipt = json.loads(receipt_output)
        except json.JSONDecodeError as exc:
            raise FoundryError("Foundry returned an invalid receipt response.") from exc
        if receipt is None or receipt == "null":
            return {
                "command": "tx inspect",
                "chain": app.network_label(chain),
                "transaction_hash": tx_hash,
                "transaction": transaction,
                "receipt": None,
                "pending": True,
            }
        return {
            "command": "tx inspect",
            "chain": app.network_label(chain),
            "transaction_hash": tx_hash,
            "transaction": transaction,
            "receipt": receipt,
            "pending": False,
        }

    raise WalletCliError(f"Unknown command '{tokens[0]}'. Use 'help' to see available commands.")


HELP_TEXT = """Commands:
  wallet new ALIAS                         Create an encrypted Foundry keystore
  wallet import ALIAS                      Import a private key through hidden prompts
  wallet list | use ALIAS | default ALIAS | info [ALIAS]
  address [ALIAS]
  chain list | info [mainnet|testnet|local]
  balance [ADDRESS]
  send DESTINATION AMOUNT [--dry-run | --yes]
  token balance CONTRACT [ADDRESS]
  token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]
  tx inspect HASH
  help | exit | quit

Amounts are exact decimal strings. Sends require an interactive terminal to unlock
the encrypted keystore; --yes skips the transaction confirmation prompt.
"""


def _parse_send_receipt(
    app: Application, output: str, kind: str
) -> tuple[dict[str, Any], str, int]:
    uncertainty = (
        f"Cast did not return a valid {kind} transaction receipt. The transaction may have been broadcast; "
        "inspect the wallet's recent activity before submitting another transfer."
    )
    if not output.strip():
        raise FoundryError(uncertainty)
    try:
        receipt = app._parse_json_result(output, "transaction receipt")
    except FoundryError as exc:
        raise FoundryError(uncertainty) from exc
    if not isinstance(receipt, dict):
        raise FoundryError(uncertainty)
    tx_hash = receipt.get("transactionHash")
    if not isinstance(tx_hash, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
        raise FoundryError(uncertainty)
    status = receipt.get("status")
    if isinstance(status, bool):
        parsed_status = None
    elif isinstance(status, int):
        parsed_status = status
    elif isinstance(status, str):
        try:
            parsed_status = int(status, 16 if status.startswith("0x") else 10)
        except ValueError:
            parsed_status = None
    else:
        parsed_status = None
    if parsed_status not in {0, 1}:
        raise FoundryError(
            f"Cast returned transaction {tx_hash} without a valid receipt status. "
            "The transaction may have been broadcast; inspect the wallet's recent activity before submitting another transfer."
        )
    return receipt, tx_hash, parsed_status
