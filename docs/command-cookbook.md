# Command cookbook

Commands below may be typed in the interactive shell or supplied after `-c` to run once:

```bash
scripts/ethereum-wallet-cli -c 'wallet list' --json
```

For shell use, omit the outer launcher command and type the command itself. Run `help` in the shell or `scripts/ethereum-wallet-cli --help` for built-in usage.

## Manage named wallets

Create a key locally and save it as an encrypted keystore:

```text
wallet new spending
```

Import a private key through Foundry's hidden prompts:

```text
wallet import savings
```

List aliases, select one for this session, or save a default wallet for that profile:

```text
wallet list
wallet use spending
wallet default savings
wallet info
wallet info spending
address
address savings
```

Wallet aliases and addresses are public metadata. `wallet info` does not reveal the private key. Rename or delete a local alias with:

```text
wallet rename spending daily
wallet delete savings
wallet delete savings --yes
```

Deletion removes only the local encrypted keystore; on-chain funds are unaffected. It asks for confirmation unless `--yes` is given.

## Select a network

```text
chain list
chain info
```

Each launcher defaults to its own mainnet. To select a testnet or local Anvil for one process or shell, use its fixed `--network` option:

```bash
scripts/ethereum-wallet-cli --network mainnet
scripts/ethereum-wallet-cli --network testnet  # Sepolia
scripts/ethereum-wallet-cli --network local
scripts/monad-wallet-cli --network mainnet
scripts/monad-wallet-cli --network testnet    # Monad Testnet
scripts/monad-wallet-cli --network local
```

`chain list` and `chain info [mainnet|testnet|local]` only inspect the networks available in that launcher profile. The selected network does not persist to the next invocation. `--rpc-url URL` overrides the selected network's endpoint for the current process; the fixed chain ID remains in force and is checked before RPC operations. Network choices are fixed for each profile.

In JSON mode, each `chain list` entry reports `name`, `chain_id`, `rpc_url`, and `current`; `chain info` reports the same fields for one selected profile network.

## Read balances

```text
address
balance
balance 0xOtherAddress
token balance 0xTokenContract
token balance 0xTokenContract 0xOtherAddress
```

The optional address selects which account to query; it does not change which wallet signs. Token balances are queried using the token contract on the currently selected chain. Related read-only commands are:

```text
status
nonce
nonce 0xOtherAddress
gas
```

`status` verifies the network and shows the selected wallet, address, and native balance. `nonce` shows the next transaction nonce (counting pending transactions). `gas` shows the current gas price in wei and gwei; it is an estimate, not a fee guarantee.

## Simulate and send native coin

```text
send 0xRecipientAddress 0.01 --dry-run
send 0xRecipientAddress 0.01
send 0xRecipientAddress 0.01 --yes
```

The standard send estimates gas before asking for confirmation. `--yes` skips only that confirmation; signing still needs Foundry's hidden passphrase prompt in an interactive terminal, so headless signing is not supported. `--dry-run` returns the estimated gas units without signing or broadcasting; it does not quote or reserve the total fee and does not guarantee success.

## Simulate and send an ERC-20 token

```text
token balance 0xTokenContract
token send 0xTokenContract 0xRecipientAddress 2.5 --dry-run
token send 0xTokenContract 0xRecipientAddress 2.5
token send 0xTokenContract 0xRecipientAddress 2.5 --yes
```

Use the contract's actual address for the selected chain. The amount is human-readable token units and the CLI obtains token details from that contract. Check the contract on a trusted explorer or project source before sending.

Before sending, the CLI simulates the ERC-20 `transfer` call and rejects a contract that explicitly returns `false`; a successful simulation still does not prove that later execution will succeed. Tokens that return no value from `transfer` are accepted.

## Inspect a transaction

```text
tx inspect 0xTransactionHash
```

A transaction can be pending, replaced, dropped, or reverted. A submitted hash is evidence that the node accepted a broadcast request, not proof of final success. Query it again if its status is still pending.

## Shell utilities and completion

```text
help
help wallet
help send
history
history 50
clear
exit
```

`help` prints a sectioned command index; `help TOPIC` prints focused usage for a command such as `wallet`, `chain`, `status`, `send`, `token`, `tx`, `address`, `balance`, `nonce`, `gas`, or `history`. The interactive shell completes commands, subcommands, network names, transfer flags, and wallet aliases when you press Tab, and the up/down arrow keys recall earlier commands. `history` shows recent commands (default 20); the history file stores plain command text in the profile's config directory. `clear` resets the interactive terminal, and `exit` (or `quit`) leaves the shell.

Human output uses aligned labels, section titles, and tables with ANSI color on an interactive terminal; color is suppressed for redirected output and when `NO_COLOR` is set or `TERM=dumb`, so copied output stays plain. In one-shot JSON mode, `clear` returns `{"ok": true, "cleared": true}` instead of writing terminal control sequences.

## Address book

Save frequently used destinations once and use their names wherever an address is accepted:

```text
contact add alice 0xAliceAddress
contact add cold 0xColdWalletAddress
contact list
balance cold
send alice 0.01 --dry-run
contact remove alice
```

Contacts are local public metadata stored in the profile's config directory.

## Saved tokens

RPC endpoints cannot enumerate ERC-20 balances, so save the tokens you care about and list them per network:

```text
token add 0xTokenContract TT
token add 0xOtherContract
token list
token info 0xTokenContract
token remove 0xOtherContract
```

`token add` reads the symbol from the contract when you do not pass one, and `token list` reads each saved token's balance for the selected wallet.

## Allowances

Inspect and clear ERC-20 allowances:

```text
token allowance 0xTokenContract 0xSpenderAddress
token allowance 0xTokenContract 0xSpenderAddress 0xOwnerAddress
token revoke 0xTokenContract 0xSpenderAddress --dry-run
token revoke 0xTokenContract 0xSpenderAddress
```

`token revoke` resets an allowance to zero by sending an `approve` transaction, so it asks before signing unless `--yes` is given.

## Advanced reads

```text
config show
call 0xTokenContract "balanceOf(address)(uint256)" 0xWalletAddress
call 0xTokenContract "decimals()(uint8)"
checksum 0xLowercaseAddress
block latest
estimate 0xRecipientAddress 0.01
```

`config show` prints the resolved settings without any RPC request. `call` runs a read-only view function. `checksum` prints the EIP-55 form locally. `block` shows a block header. `estimate` is a native-transfer gas estimate that never signs.

## Transaction log and watching

RPC endpoints cannot list a wallet's history, so the CLI records the hashes it broadcasts itself:

```text
tx list
tx list 50
tx watch 0xTransactionHash
```

`tx list` filters the local log to the current network. `tx watch` polls until the transaction is mined and then prints its receipt.

## Watch-only wallets and health checks

```text
wallet watch cold 0xColdWalletAddress
balance cold
wallet verify
wallet verify cold
wallet delete cold --yes
```

A watch-only wallet has no keystore and can be read from but never signs; signing commands refuse it. `wallet verify` re-checks each local keystore for readability, address consistency, and permissions, which is useful before relying on a backup.

## Advanced help

The common `help` index hides the advanced commands above. Run `help --verbose` (or start the shell with `--verbose`) to show them, and `help TOPIC` for one focused page such as `help send`, `help token`, or `help contact`.

## Supported network mapping

The `--network` values map to these fixed chains:

| Launcher | Network | Chain | Chain ID |
| --- | --- | --- | ---: |
| Ethereum | `mainnet` | Ethereum | 1 |
| Ethereum | `testnet` | Sepolia | 11155111 |
| Ethereum | `local` | Anvil | 31337 |
| Monad | `mainnet` | Monad | 143 |
| Monad | `testnet` | Monad Testnet | 10143 |
| Monad | `local` | Anvil | 31337 |

Built-in RPC defaults are shown in [chain and wallet concepts](chains-and-wallets.md). Use `--rpc-url` when you have another endpoint for the same chain. The CLI checks the endpoint's chain ID, but that does not prove that its operator is trustworthy.

## JSON automation

Request structured output for one-shot commands. Choose the Ethereum or Monad launcher according to the separate wallet profile you want to query:

```bash
scripts/ethereum-wallet-cli -c 'chain list' --json
scripts/ethereum-wallet-cli -c 'wallet list' --json
scripts/ethereum-wallet-cli -c 'balance' --json
scripts/ethereum-wallet-cli -c 'tx inspect 0xTransactionHash' --json
scripts/monad-wallet-cli -c 'balance' --json
```

Treat output as data from the configured RPC. Do not put secrets in command strings or scripts. The signing password remains an interactive prompt even when the command is launched with `-c`. The two launchers use independent config directories, so a wallet imported into the Ethereum profile is not automatically present in the Monad profile.

Successful JSON output has an `ok: true` field, a `command` name, and command-specific fields. For example, a native balance response looks like:

```json
{
  "ok": true,
  "command": "balance",
  "chain": "mainnet",
  "address": "0x...",
  "balance_base_units": "1000000000000000000",
  "balance_native": "1"
}
```

Errors from command execution are written as `{"ok": false, "error": "..."}` to standard error and exit with status 1. Blockchain quantities and token raw amounts are strings so callers can preserve integer precision. JSON mode applies to a one-shot command; the interactive shell uses human-readable output.

Every command also writes a trace to standard error after it completes or fails. Each line is `[wrapper]` followed by the shell-quoted Cast argv; the trace includes chain-ID checks, simulations, and sends. Commands handled locally print `[wrapper] No external command ran (local command).` Custom and local RPC URLs are masked as `<redacted-rpc-url>`; bundled public endpoint URLs remain visible. Private keys and passphrases are never included. For automation, parse successful JSON from standard output and keep standard error separate. On failure, use the exit status and inspect the error JSON record and trace in standard error instead of parsing the whole stream as one JSON value.
