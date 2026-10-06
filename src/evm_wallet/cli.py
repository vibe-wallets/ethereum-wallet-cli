"""Argument parsing, one-shot execution, and the interactive shell."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Callable, Sequence, TextIO

from .app import Application, execute
from .chains import PROFILE_NETWORKS
from .completion import complete_candidates
from .errors import WalletCliError
from .help import help_text
from .history import HISTORY_LIMIT, append_history, read_history
from .human import (
    CLEAR_SCREEN,
    action_preview,
    color,
    format_transaction_receipt,
    key_value_rows,
    network_label,
    section_title,
    shorten_address,
    style_help,
    table,
)

try:  # GNU readline is optional; the shell still works without line editing.
    import readline
except ImportError:  # pragma: no cover - depends on the Python build
    readline = None  # type: ignore[assignment]


def _parser(
    prog: str,
    config_env: str,
    config_subdir: str,
    network_choices: Sequence[str],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="A small Ethereum-compatible wallet CLI backed by Foundry Cast.",
        epilog="Use -c 'COMMAND' for one-shot shell syntax, or pass command words directly.",
    )
    parser.add_argument("-c", "--command", help="run a single quoted command")
    parser.add_argument(
        "--config-dir",
        help=f"wallet state directory (default: {config_env} or XDG config path '{config_subdir}')",
    )
    parser.add_argument(
        "--network",
        choices=network_choices,
        help="select mainnet, testnet, or local for this run or shell session",
    )
    parser.add_argument(
        "--rpc-url", help="override the selected chain's RPC URL for this run or shell session"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print one-shot command output as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show advanced commands and details",
    )
    parser.add_argument("--version", action="version", version=f"{prog} 0.1.0")
    return parser


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def _render_human(result: dict[str, object], output: TextIO | None = None) -> None:
    """Print one command result in the human-readable style."""
    output = output or sys.stdout
    command = result.get("command")
    if command == "help":
        print(style_help(result.get("text", help_text()), stream=output), file=output)
    elif command == "exit":
        return
    elif command == "clear":
        if _is_tty(output):
            output.write(CLEAR_SCREEN)
            output.flush()
    elif command == "wallet list":
        wallets = result.get("wallets", [])
        if not wallets:
            message = "No wallets. Use 'wallet new ALIAS' or 'wallet import ALIAS'."
            print(color(message, "muted", stream=output), file=output)
        else:
            rows = []
            for wallet in wallets:
                markers = []
                if wallet["default"]:
                    markers.append("default")
                if wallet["current"]:
                    markers.append("current")
                if wallet.get("watch_only"):
                    markers.append("watch")
                tags = f"[{', '.join(markers)}]" if markers else ""
                rows.append([wallet["alias"], wallet["address"], tags])
            print(section_title("WALLETS", stream=output), file=output)
            print(table(rows, ["ALIAS", "ADDRESS", "TAGS"], stream=output), file=output)
    elif command == "chain list":
        rows = []
        for chain in result.get("chains", []):
            rows.append(
                [
                    f"{chain['name']}: chain {chain['chain_id']}",
                    chain["rpc_url"],
                    "[current]" if chain["current"] else "",
                ]
            )
        print(section_title("NETWORKS", stream=output), file=output)
        print(table(rows, stream=output), file=output)
    elif command == "chain info":
        rows = [
            ("Network", result["name"]),
            ("Chain ID", str(result["chain_id"])),
            ("RPC URL", result["rpc_url"]),
            ("Current", "yes" if result["current"] else "no"),
        ]
        print(section_title("NETWORK", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "status":
        rows = [
            ("Network", network_label(str(result["network"]), stream=output)),
            (
                "Wallet",
                f"{result['wallet']} ({result['address']})"
                if "wallet" in result
                else color("none selected", "warning", stream=output),
            ),
            ("Chain ID", str(result["chain_id"])),
            ("RPC URL", result["rpc_url"]),
        ]
        if "balance_native" in result:
            rows.append(("Balance", result["balance_native"], "emphasis"))
        print(section_title("STATUS", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "balance":
        rows = [
            ("Address", result["address"]),
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Balance", result["balance_native"], "emphasis"),
        ]
        print(section_title("NATIVE BALANCE", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "token balance":
        rows = [
            ("Contract", result["contract"]),
            ("Address", result["address"]),
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Decimals", str(result["decimals"])),
            ("Balance", result["balance"], "emphasis"),
        ]
        print(section_title("TOKEN BALANCE", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "token info":
        rows = [
            ("Name", str(result["name"] or "unknown")),
            ("Symbol", str(result["symbol"] or "unknown")),
            ("Contract", result["contract"]),
            ("Decimals", str(result["decimals"])),
            ("Total supply", result["total_supply"], "emphasis"),
        ]
        print(section_title("TOKEN INFO", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "token list":
        tokens = result.get("tokens", [])
        print(section_title("SAVED TOKENS", stream=output), file=output)
        if not tokens:
            message = "No saved tokens for this network. Use 'token add CONTRACT'."
            print(color(message, "muted", stream=output), file=output)
        else:
            rows = [
                [str(token["symbol"] or "-"), token["contract"], token["balance"]]
                for token in tokens
            ]
            print(table(rows, ["SYMBOL", "CONTRACT", "BALANCE"], stream=output), file=output)
    elif command == "token add":
        saved = f"Token '{result['contract']}' saved"
        symbol = f" as {result['symbol']}" if result.get("symbol") else ""
        print(f"{color(saved, 'success', stream=output)}{symbol}.", file=output)
    elif command == "token remove":
        removed = f"Token '{result['contract']}' forgotten"
        print(f"{color(removed, 'success', stream=output)}.", file=output)
    elif command == "token allowance":
        rows = [
            ("Contract", result["contract"]),
            ("Owner", result["owner"]),
            ("Spender", result["spender"]),
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Allowance", result["allowance"], "emphasis"),
            ("Exact units", str(result["allowance_raw"])),
        ]
        print(section_title("TOKEN ALLOWANCE", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "token revoke" and result.get("dry_run"):
        preview = action_preview(
            "REVOKE APPROVAL · TRANSACTION PREVIEW",
            [
                ("Network", network_label(str(result["chain"]), stream=output)),
                ("From", f"{result['from_wallet']} ({result['from']})"),
                ("Contract", result["contract"]),
                ("Spender", result["spender"]),
                ("New allowance", "0", "emphasis"),
                ("Estimated gas", str(result["estimated_gas"])),
            ],
            stream=output,
        )
        print(preview, file=output)
    elif command == "nonce":
        rows = [
            ("Address", result["address"]),
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Nonce", str(result["nonce"]), "emphasis"),
        ]
        print(section_title("NONCE", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "gas":
        rows = [
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Chain ID", str(result["chain_id"])),
            ("Gas price", f"{result['gas_price_gwei']} gwei", "emphasis"),
            (
                "Base fee",
                f"{result['base_fee_gwei']} gwei"
                if result.get("base_fee_gwei") is not None
                else color("unavailable", "muted", stream=output),
            ),
            ("Exact wei", str(result["gas_price_wei"])),
        ]
        print(section_title("GAS", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "config show":
        rows = [
            ("Profile", result["profile"]),
            ("Config dir", result["config_dir"]),
            ("Network", network_label(str(result["network"]), stream=output)),
            ("Chain ID", str(result["chain_id"])),
            ("RPC URL", result["rpc_url"]),
            (
                "Wallet",
                f"{result['wallet']} ({result['address']})"
                if result.get("wallet")
                else color("none selected", "warning", stream=output),
            ),
            ("Default wallet", str(result["default_wallet"] or "-")),
            ("Watch only", "yes" if result["watch_only"] else "no"),
            ("Contacts", str(result["contact_count"])),
            ("Saved tokens", str(result["saved_token_count"])),
        ]
        print(section_title("CONFIG", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "checksum":
        print(result["checksum"], file=output)
    elif command == "call":
        rows = [
            ("Contract", result["contract"]),
            ("Signature", result["signature"]),
            ("Network", network_label(str(result["chain"]), stream=output)),
            ("Result", result["result"], "emphasis"),
        ]
        print(section_title("CALL", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "block":
        gas = (
            f"{result['gas_used']} / {result['gas_limit']}"
            if result.get("gas_used") is not None and result.get("gas_limit") is not None
            else "unknown"
        )
        rows = [
            ("Number", str(result["number"] or "unknown")),
            ("Hash", str(result["hash"] or "unknown")),
            (
                "Timestamp",
                str(result["timestamp"]) if result["timestamp"] is not None else "unknown",
            ),
            (
                "Transactions",
                str(result["transaction_count"])
                if result["transaction_count"] is not None
                else "unknown",
            ),
            ("Gas used", gas),
            (
                "Base fee",
                f"{result['base_fee_per_gas']} wei"
                if result.get("base_fee_per_gas") is not None
                else "unavailable",
            ),
        ]
        print(section_title("BLOCK", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "contact list":
        contacts = result.get("contacts", [])
        print(section_title("CONTACTS", stream=output), file=output)
        if not contacts:
            print(
                color("No contacts saved. Use 'contact add NAME ADDRESS'.", "muted", stream=output),
                file=output,
            )
        else:
            rows = [[contact["name"], contact["address"]] for contact in contacts]
            print(table(rows, ["NAME", "ADDRESS"], stream=output), file=output)
    elif command == "contact add":
        saved = f"Contact '{result['name']}' saved"
        print(f"{color(saved, 'success', stream=output)} at {result['address']}.", file=output)
    elif command == "contact remove":
        removed = f"Contact '{result['name']}' removed"
        print(f"{color(removed, 'success', stream=output)}.", file=output)
    elif command in {"send", "estimate"} and result.get("dry_run"):
        title = (
            "ESTIMATE NATIVE TRANSFER"
            if command == "estimate"
            else "SEND NATIVE · TRANSACTION PREVIEW"
        )
        preview = action_preview(
            title,
            [
                ("Network", network_label(str(result["chain"]), stream=output)),
                ("From", f"{result['from_wallet']} ({result['from']})"),
                ("To", result["to"]),
                ("Amount", result["amount"], "emphasis"),
                ("Estimated gas", str(result["estimated_gas"])),
            ],
            stream=output,
        )
        print(preview, file=output)
    elif command == "token send" and result.get("dry_run"):
        preview = action_preview(
            "SEND TOKEN · TRANSACTION PREVIEW",
            [
                ("Network", network_label(str(result["chain"]), stream=output)),
                ("From", f"{result['from_wallet']} ({result['from']})"),
                ("Contract", result["contract"]),
                ("To", result["to"]),
                ("Amount", result["amount"], "emphasis"),
                ("Decimals", str(result["decimals"])),
                ("Estimated gas", str(result["estimated_gas"])),
            ],
            stream=output,
        )
        print(preview, file=output)
    elif command == "tx inspect":
        print(section_title("TRANSACTION", stream=output), file=output)
        if result["pending"]:
            message = f"Transaction {result['transaction_hash']} is pending on {result['chain']}."
            print(color(message, "warning", stream=output), file=output)
        else:
            print(f"Transaction: {result['transaction_hash']} on {result['chain']}", file=output)
            print(json.dumps(result["transaction"], indent=2, sort_keys=True), file=output)
            print(section_title("RECEIPT", stream=output), file=output)
            print(json.dumps(result["receipt"], indent=2, sort_keys=True), file=output)
    elif command == "tx list":
        records = result.get("transactions", [])
        print(section_title("RECORDED TRANSACTIONS", stream=output), file=output)
        if not records:
            message = (
                "No recorded transactions for this network; only sends from this CLI are logged."
            )
            print(color(message, "muted", stream=output), file=output)
        else:
            rows = [
                [
                    str(record.get("hash", "")),
                    str(record.get("kind", "tx")),
                    str(record.get("to") or record.get("spender") or ""),
                    str(record.get("amount", "")),
                ]
                for record in reversed(records)
            ]
            print(table(rows, ["HASH", "KIND", "TO/SPENDER", "AMOUNT"], stream=output), file=output)
    elif command == "tx watch":
        if result["pending"]:
            message = (
                f"Transaction {result['transaction_hash']} is still pending on {result['chain']}."
            )
            print(color(message, "warning", stream=output), file=output)
        else:
            print(f"Transaction: {result['transaction_hash']} on {result['chain']}", file=output)
            print(json.dumps(result["receipt"], indent=2, sort_keys=True), file=output)
    elif command == "history":
        entries = result.get("entries", [])
        print(section_title("HISTORY", stream=output), file=output)
        if not entries:
            print(color("No history yet.", "muted", stream=output), file=output)
        else:
            width = len(str(len(entries)))
            for index, entry in enumerate(entries, start=1):
                number = color(f"{index:>{width}}", "muted", stream=output)
                print(f"  {number}  {entry}", file=output)
    elif command in {"wallet new", "wallet import"}:
        ready = f"Wallet '{result['alias']}' is ready"
        print(
            f"{color(ready, 'success', stream=output)} at {result['address']}.",
            file=output,
        )
    elif command == "wallet info":
        rows = [
            ("Alias", result["alias"]),
            ("Address", result["address"]),
            (
                "Encrypted keystore",
                result["keystore"] if result.get("keystore") else "watch-only",
            ),
        ]
        print(section_title("WALLET", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "wallet watch":
        watched = f"Wallet '{result['alias']}' is watch-only"
        print(
            f"{color(watched, 'success', stream=output)} at {result['address']}.",
            file=output,
        )
    elif command == "wallet verify":
        wallets = result.get("wallets", [])
        print(section_title("WALLET HEALTH", stream=output), file=output)
        if not wallets:
            print(color("No wallets to verify.", "muted", stream=output), file=output)
        else:
            rows = [
                [
                    entry["alias"],
                    entry["address"],
                    "watch-only" if entry["watch_only"] else "keystore",
                    "ok" if entry["valid"] else f"invalid: {entry.get('error', '')}",
                ]
                for entry in wallets
            ]
            print(table(rows, ["ALIAS", "ADDRESS", "TYPE", "STATUS"], stream=output), file=output)
    elif command == "wallet rename":
        renamed = f"Wallet '{result['old_alias']}' renamed to '{result['alias']}'"
        print(
            f"{color(renamed, 'success', stream=output)} at {result['address']}.",
            file=output,
        )
    elif command == "wallet delete":
        deleted = f"Wallet '{result['alias']}' deleted locally"
        print(f"{color(deleted, 'success', stream=output)}.", file=output)
    elif command == "address":
        print(result["address"], file=output)
    elif command in {"wallet use", "wallet default"}:
        selected = f"Wallet '{result['alias']}' selected"
        print(
            f"{color(selected, 'success', stream=output)} at {result['address']}.",
            file=output,
        )
    elif command in {"send", "token send", "token revoke"}:
        if command == "send":
            action = "Transaction"
        elif command == "token send":
            action = "Token transaction"
        else:
            action = "Approval revocation"
        rows = [("Wallet", f"{result['wallet']} ({result['from']})")]
        if command == "token revoke":
            rows.extend(
                [
                    ("Contract", result["contract"]),
                    ("Spender", result["spender"]),
                    ("New allowance", "0", "emphasis"),
                ]
            )
        else:
            rows.extend(
                [
                    ("To", result["to"]),
                    ("Amount", result["amount"], "emphasis"),
                ]
            )
        rows.append(("Estimated gas", str(result.get("estimated_gas") or "unknown")))
        print(
            format_transaction_receipt(
                action=action,
                network=str(result["chain"]),
                rows=rows,
                signature=result.get("transaction_hash"),
                stream=output,
            ),
            file=output,
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True), file=output)


def _print_error(message: str, *, json_output: bool, output: TextIO | None = None) -> None:
    """Print a user-facing error as JSON or as a styled human line."""
    output = output or sys.stderr
    if json_output:
        print(json.dumps({"ok": False, "error": message}, sort_keys=True), file=output)
    else:
        label = color("Error", "error", stream=output)
        print(f"{label}: {message}", file=output)


def _run_one(tokens: list[str], app: Application, *, json_output: bool) -> int:
    """Run one command, then flush its Cast trace to stderr."""
    app.cast.clear_trace()
    try:
        result = execute(tokens, app, json_output=json_output)
        if json_output:
            print(json.dumps({"ok": True, **result}, sort_keys=True))
        else:
            _render_human(result)
        return 0
    except WalletCliError as exc:
        _print_error(str(exc), json_output=json_output)
        return 1
    finally:
        app.cast.flush_trace()


def _shell_prompt(app: Application, chain_name: str, wallet_alias: str) -> str:
    """Build the coloured interactive prompt for the selected network and wallet."""
    chain_tone = "warning" if chain_name == "mainnet" else "info"
    wallet_tone = "warning" if wallet_alias == "no-wallet" else "success"
    chain = color(chain_name, chain_tone, stream=sys.stdout)
    wallet = color(wallet_alias, wallet_tone, stream=sys.stdout)
    return f"{app.profile}[{chain}]({wallet})> "


def _print_banner(app: Application, state: dict[str, object]) -> None:
    """Show the selected wallet and network once when the shell starts."""
    titles = {"ethereum": "Ethereum Wallet CLI", "monad": "Monad Wallet CLI"}
    print(section_title(titles.get(app.profile, "Wallet CLI"), stream=sys.stdout))
    alias = app.active_wallet_alias(state)
    if alias and alias in state["wallets"]:
        address = state["wallets"][alias]["address"]
        print(
            key_value_rows([("Wallet", f"{alias} ({shorten_address(address)})")], stream=sys.stdout)
        )
    else:
        label = color("Wallet", "muted", stream=sys.stdout)
        value = color("none selected", "warning", stream=sys.stdout)
        print(f"{label}: {value}")
    print(
        key_value_rows(
            [("Network", network_label(app.network_name, stream=sys.stdout))],
            stream=sys.stdout,
        )
    )
    print("Type `help` for commands, press Tab to complete, or `status` to refresh.\n")


def _wallet_aliases(app: Application) -> list[str]:
    """Return configured wallet aliases for completion, or none on any config error."""
    try:
        return sorted(app.config()["wallets"])
    except WalletCliError:
        return []


def _completer(app: Application) -> Callable[[str, int], str | None]:
    """Build a readline completer bound to the current application."""

    def complete(text: str, state: int) -> str | None:
        if readline is None:  # pragma: no cover - only without readline
            return None
        begin = readline.get_begidx()
        tokens = readline.get_line_buffer()[:begin].split()
        matches = complete_candidates(tokens, text, _wallet_aliases(app))
        return matches[state] if state < len(matches) else None

    return complete


def _setup_readline(app: Application) -> None:
    """Enable Tab completion, history recall, and persisted history when available."""
    if readline is None:  # pragma: no cover - only without readline
        return
    readline.set_completer_delims(" \t\n")
    readline.set_completer(_completer(app))
    readline.parse_and_bind("tab: complete")
    readline.set_history_length(HISTORY_LIMIT)
    try:
        readline.read_history_file(str(app.history_path))
    except (OSError, ValueError):
        pass


def _shell(app: Application) -> int:
    """Read commands from an interactive terminal until exit or EOF."""
    banner_state = app.config()
    _print_banner(app, banner_state)
    app.history = read_history(app.history_path)
    _setup_readline(app)
    while True:
        try:
            state = app.config()
            app.active_chain(state)
            chain_name = app.network_name
            wallet_alias = app.active_wallet_alias(state) or "no-wallet"
            line = input(_shell_prompt(app, chain_name, wallet_alias))
        except EOFError:
            print(file=sys.stdout)
            return 0
        except KeyboardInterrupt:
            print(file=sys.stdout)
            return 130
        except WalletCliError as exc:
            _print_error(str(exc), json_output=False)
            return 1
        app.cast.clear_trace()
        try:
            tokens = shlex.split(line, comments=False, posix=True)
        except ValueError as exc:
            _print_error(f"cannot parse command: {exc}", json_output=False)
            app.cast.flush_trace()
            continue
        if not tokens:
            continue
        app.history.append(line)
        append_history(app.history_path, line)
        try:
            result = execute(tokens, app)
            if result.get("command") == "exit":
                return 0
            _render_human(result)
        except WalletCliError as exc:
            _print_error(str(exc), json_output=False)
        except ValueError as exc:
            _print_error(f"command failed: {exc}", json_output=False)
        finally:
            app.cast.flush_trace()


def main(
    argv: Sequence[str] | None = None,
    *,
    profile: str = "ethereum",
    prog: str = "ethereum-wallet-cli",
    config_env: str = "ETHEREUM_WALLET_CONFIG_DIR",
    network_env: str = "ETHEREUM_WALLET_NETWORK",
    rpc_env: str = "ETHEREUM_WALLET_RPC_URL",
    config_subdir: str = "ethereum-wallet-cli",
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    profile_networks = PROFILE_NETWORKS.get(profile)
    if profile_networks is None:
        _print_error(f"Unknown CLI profile '{profile}'.", json_output=False)
        print("[wrapper] No external command ran (local command).", file=sys.stderr)
        return 2
    parser = _parser(prog, config_env, config_subdir, tuple(profile_networks))
    try:
        namespace, command_words = parser.parse_known_args(args)
        json_output = bool(namespace.json_output)
        if namespace.command is not None:
            if command_words:
                parser.error("-c/--command cannot be combined with direct command arguments")
            try:
                command_words = shlex.split(namespace.command, comments=False, posix=True)
            except ValueError as exc:
                parser.error(f"invalid command string: {exc}")
        if "--json" in command_words:
            json_output = True
            command_words = [word for word in command_words if word != "--json"]
    except SystemExit as exc:
        print("[wrapper] No external command ran (local command).", file=sys.stderr)
        return int(exc.code or 0)

    try:
        config_dir = namespace.config_dir or os.environ.get(config_env)
        if config_dir is None:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            base = (
                os.path.expanduser(xdg)
                if xdg and os.path.isabs(xdg)
                else os.path.join(os.path.expanduser("~"), ".config")
            )
            config_dir = os.path.join(base, config_subdir)
        network_name = namespace.network or os.environ.get(network_env) or "mainnet"
        if network_name not in profile_networks:
            raise WalletCliError(f"Network '{network_name}' is not available in the {profile} CLI.")
        chain_name = profile_networks[network_name]
        rpc_url = namespace.rpc_url or os.environ.get(rpc_env)
        app = Application(
            config_dir,
            chain_name=chain_name,
            rpc_url=rpc_url,
            profile=profile,
            network_name=network_name,
        )
        app.verbose = bool(namespace.verbose)
        app.active_chain()
    except WalletCliError as exc:
        _print_error(str(exc), json_output=json_output)
        print("[wrapper] No external command ran (local command).", file=sys.stderr)
        return 1

    if command_words:
        return _run_one(command_words, app, json_output=json_output)
    if json_output:
        _print_error("--json applies to one-shot commands; pass a command or -c", json_output=False)
        print("[wrapper] No external command ran (local command).", file=sys.stderr)
        return 2
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        _print_error(
            "interactive shell requires a terminal; pass a command or use -c", json_output=False
        )
        print("[wrapper] No external command ran (local command).", file=sys.stderr)
        return 2
    return _shell(app)


def monad_main(argv: Sequence[str] | None = None) -> int:
    return main(
        argv,
        profile="monad",
        prog="monad-wallet-cli",
        config_env="MONAD_WALLET_CONFIG_DIR",
        network_env="MONAD_WALLET_NETWORK",
        rpc_env="MONAD_WALLET_RPC_URL",
        config_subdir="monad-wallet-cli",
    )


if __name__ == "__main__":
    raise SystemExit(main())
