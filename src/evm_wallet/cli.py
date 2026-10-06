from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Sequence, TextIO

from .app import HELP_TEXT, Application, execute
from .chains import PROFILE_NETWORKS
from .errors import WalletCliError
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
    output = output or sys.stdout
    command = result.get("command")
    if command == "help":
        print(style_help(result.get("text", HELP_TEXT), stream=output), file=output)
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
    elif command == "send" and result.get("dry_run"):
        preview = action_preview(
            "SEND NATIVE · TRANSACTION PREVIEW",
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
            ("Encrypted keystore", result["keystore"]),
        ]
        print(section_title("WALLET", stream=output), file=output)
        print(key_value_rows(rows, stream=output), file=output)
    elif command == "address":
        print(result["address"], file=output)
    elif command in {"wallet use", "wallet default"}:
        selected = f"Wallet '{result['alias']}' selected"
        print(
            f"{color(selected, 'success', stream=output)} at {result['address']}.",
            file=output,
        )
    elif command in {"send", "token send"}:
        action = "Transaction" if command == "send" else "Token transaction"
        rows = [
            ("Wallet", f"{result['wallet']} ({result['from']})"),
            ("To", result["to"]),
            ("Amount", result["amount"], "emphasis"),
            ("Estimated gas", str(result.get("estimated_gas") or "unknown")),
        ]
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
    output = output or sys.stderr
    if json_output:
        print(json.dumps({"ok": False, "error": message}, sort_keys=True), file=output)
    else:
        label = color("Error", "error", stream=output)
        print(f"{label}: {message}", file=output)


def _run_one(tokens: list[str], app: Application, *, json_output: bool) -> int:
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
    chain_tone = "warning" if chain_name == "mainnet" else "info"
    wallet_tone = "warning" if wallet_alias == "no-wallet" else "success"
    chain = color(chain_name, chain_tone, stream=sys.stdout)
    wallet = color(wallet_alias, wallet_tone, stream=sys.stdout)
    return f"{app.profile}[{chain}]({wallet})> "


def _print_banner(app: Application, state: dict[str, object]) -> None:
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
    print("Type `help` for commands, or `balance` after selecting a wallet.\n")


def _shell(app: Application) -> int:
    banner_state = app.config()
    _print_banner(app, banner_state)
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
