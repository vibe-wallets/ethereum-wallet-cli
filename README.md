# Ethereum, Monad, and BNB Smart Chain Wallet CLIs

`ethereum-wallet-cli`, `monad-wallet-cli`, and `bsc-wallet-cli` are small personal command-line wallets for Ethereum, Monad, and BNB Smart Chain. All three use Foundry Cast for key creation/import, encrypted keystores, signing, RPC requests, and transaction handling. The Docker image packages the CLI with pinned Cast binaries; each wrapper has its own wallet store and fixed network choices.

All launchers pull `ghcr.io/vibe-wallets/ethereum-wallet-cli:main` before starting. No local build is required:

```bash
scripts/ethereum-wallet-cli
scripts/monad-wallet-cli
scripts/bsc-wallet-cli
```

Pull failures stop the launcher instead of running an older cached image. The GHCR container package may be private; when it is, the launcher authenticates with the caller's existing `ghcr.io` Docker credentials, and an administrator can make it public in the package settings for anonymous pulls. CI promotes the `main` tag only after pulling and testing the published image on a fresh runner. For local development, build with `make build` and explicitly select `ethereum-wallet-cli:local` using the matching profile's image environment variable.

The three CLIs use separate state directories and do not share wallet aliases or encrypted keys. By default, Ethereum state lives in `~/.config/ethereum-wallet-cli`, Monad state in `~/.config/monad-wallet-cli`, and BNB Smart Chain state in `~/.config/bsc-wallet-cli` (under `$XDG_CONFIG_HOME` when set). Override them with `ETHEREUM_WALLET_CONFIG_DIR`, `MONAD_WALLET_CONFIG_DIR`, and `BSC_WALLET_CONFIG_DIR`, respectively. Each directory is mounted at `/data` inside its disposable container. `ETHEREUM_WALLET_IMAGE`, `MONAD_WALLET_IMAGE`, and `BSC_WALLET_IMAGE` can select another image independently; the local tag is an explicit developer override.

For a first wallet, enter these commands in the shell. Secret entry happens through Foundry's hidden prompts:

```text
wallet new daily
wallet list
wallet use daily
address
balance
```

To import an existing private key, use `wallet import savings`; the prompt accepts the key without putting it in shell history or the process argument list. Keep your original key backup independently. For a key created with `wallet new`, back up the active profile's full state directory and keep its keystore password separately; this CLI does not export the generated raw key.

To use the Monad or BNB Smart Chain CLI, run `scripts/monad-wallet-cli` or `scripts/bsc-wallet-cli`, then create or import a wallet in that separate profile. A `wallet new` command in each profile creates different keys. To use one private key on multiple networks, import it separately into each profile.

Run a single command without opening the shell with `-c`; `--json` requests machine-readable output:

```bash
scripts/ethereum-wallet-cli -c 'wallet list' --json
scripts/ethereum-wallet-cli -c 'chain list' --json
scripts/monad-wallet-cli -c 'balance' --json
scripts/bsc-wallet-cli -c 'balance' --json
```

The Ethereum CLI starts on Ethereum mainnet, the Monad CLI starts on Monad mainnet, and the BNB Smart Chain CLI starts on BNB Smart Chain mainnet. Select testnet for one run with `scripts/ethereum-wallet-cli --network testnet`, `scripts/monad-wallet-cli --network testnet`, or `scripts/bsc-wallet-cli --network testnet`. `--network local` selects local Anvil in any profile. `--rpc-url URL` can override the endpoint for the selected network; the CLI still checks the fixed chain ID before network operations. Network choice lasts for that invocation or interactive shell session.

Network mappings are fixed per entrypoint: Ethereum `mainnet` is chain `1`, `testnet` is Sepolia (`11155111`), and `local` is Anvil (`31337`); Monad `mainnet` is chain `143`, `testnet` is Monad Testnet (`10143`), and `local` is Anvil (`31337`); BNB Smart Chain `mainnet` is chain `56`, `testnet` is BSC Testnet (`97`), and `local` is Anvil (`31337`). Run `chain list` or `chain info` to inspect the networks supported by the selected profile and their RPC endpoints.

## What it supports

- Create or import named wallets, list them, select a wallet for the session, choose a saved default, and inspect wallet metadata. Each entrypoint has its own wallet store.
- Choose mainnet, testnet, or local Anvil through each entrypoint's fixed network mapping.
- Read a native coin balance, an ERC-20 balance, the next nonce, or the current gas price.
- Refresh a `status` overview of the network, selected wallet, and native balance.
- Send native coin or an ERC-20 transfer, with a dry-run estimate or an explicit confirmation.
- Rename or delete local wallet aliases; deletion never touches on-chain funds.
- Inspect transaction details by transaction hash.
- Use an interactive shell with Tab completion and persisted history, direct argv commands, or one-shot `-c` commands; request JSON output with `--json`.

The tool does not implement its own cryptography, ABI encoder, or JSON-RPC client. It does not support seed phrases, hardware wallets, arbitrary contract transaction construction, swapping, bridging, staking, or smart-account flows.

## Commands

```text
wallet new ALIAS
wallet import ALIAS
wallet list
wallet use ALIAS
wallet default ALIAS
wallet info [ALIAS]
wallet rename OLD NEW
wallet delete ALIAS [--yes]
address [ALIAS]
chain list
chain info [mainnet|testnet|local]
status
balance [ADDRESS]
nonce [ADDRESS]
gas
token balance CONTRACT [ADDRESS]
send DESTINATION AMOUNT [--dry-run | --yes]
token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]
tx inspect HASH
history [COUNT]
help [TOPIC]
clear
```

The top-level options are `-c 'COMMAND'` / `--command 'COMMAND'` for a one-shot command, `--network mainnet|testnet|local` to choose a profile-supported network, `--rpc-url URL` to override its RPC endpoint, `--json` for JSON output, `--config-dir PATH` for an explicit state directory, and `--version`. Direct command arguments are also supported; when no command is supplied, the CLI opens its interactive shell. JSON output is available for one-shot commands only. Fresh invocations default to the entrypoint's mainnet; a selected network applies to that invocation or shell only.

`wallet use ALIAS` selects the wallet for the current session; `wallet default ALIAS` stores the profile's saved wallet default. Wallet defaults are separate between the Ethereum, Monad, and BNB Smart Chain profiles. `wallet rename` renames a local alias, and `wallet delete` removes a local encrypted keystore after confirmation; neither touches on-chain funds.

The command list above is the common set. Advanced commands are hidden from `help`
by default; run `help --verbose`, or start the shell with `--verbose`, to show them:

```text
config show
call CONTRACT SIGNATURE [ARGS...]
checksum ADDRESS
block [NUMBER|latest]
contact add NAME ADDRESS
contact list
contact remove NAME
estimate DESTINATION AMOUNT
token info CONTRACT
token list [ADDRESS]
token add CONTRACT [SYMBOL]
token remove CONTRACT
token allowance CONTRACT SPENDER [OWNER]
token revoke CONTRACT SPENDER [--dry-run | --yes]
tx list [COUNT]
tx watch HASH
wallet watch ALIAS ADDRESS
wallet verify [ALIAS]
```

Saved contacts, saved tokens, and the local transaction log are public metadata kept in the profile's config directory. `wallet watch` adds a read-only address that can be queried but never signs.

In the interactive shell, Tab completes commands, subcommands, networks, flags, and wallet aliases, and `history` shows recent commands. Run `help TOPIC` (for example `help wallet` or `help send`) for focused usage. History is stored as plain command text in the profile's config directory.

After each command succeeds or fails, the CLI prints the underlying Foundry Cast invocations to standard error, including chain checks, simulations, and sends. Local commands explicitly report when no external command ran. Custom and local RPC URLs are masked in the trace; bundled public endpoint URLs remain visible. Private keys and passphrases are never printed. With `--json`, standard output remains the JSON result; standard error may contain the trace or error details.

Human output uses aligned labels, section titles, and tables, plus ANSI color on an interactive terminal. Color is disabled for redirected output and when `NO_COLOR` is set or `TERM=dumb`, so piping and JSON mode stay plain. `clear` resets the screen in an interactive shell and reports `{"ok": true, "cleared": true}` in JSON mode.

See [the command cookbook](docs/command-cookbook.md) for complete examples and [getting started](docs/getting-started.md) for the initial setup. Run any wrapper with `--help`, or use `help` inside the shell.

## Build, tests, and development

```bash
make build              # Build the local Docker image
make test               # Offline Python tests
make test-integration   # Build image and run isolated Anvil integration tests
make test-docker        # Build image and run full Docker end-to-end tests
make test-published     # Pull and test a published image (no local build)
make lint               # Ruff, Python compile, and shell syntax checks
make format            # Format source and tests (Ruff)
make format-check      # Check Python formatting
make run ARGS='--help'  # Run the containerized CLI
make run-monad          # Launch the Monad CLI
make run-bsc            # Launch the BNB Smart Chain CLI
```

Integration tests use local Anvil nodes, test-only keys, and a test ERC-20 fixture. They do not contact live networks or use real funds or existing personal wallets. See [developer and test notes](docs/development.md) for image-promotion gates and full Docker end-to-end coverage, and [architecture](docs/architecture.md).

## Security notes

Keystores and configuration are saved under the mounted host directory with restrictive permissions. A keystore is encrypted, but wallet aliases and public addresses are visible in configuration. Losing the keystore password can make that encrypted copy unusable. Keep an independent backup of the full state directory and store its password separately.

Private keys and passwords are not accepted as command arguments or environment variables. The CLI asks Foundry to prompt for secrets. RPC providers receive public addresses and requests, and may log them. A dry-run reports an estimated gas amount, not a guaranteed transaction fee or execution result. Once a send is submitted, check its hash/status before deciding whether to try again; the CLI does not automatically retry a broadcast.

This is personal-use software, not audited wallet software. Read [security and operations](docs/security.md) before storing valuable keys.

## Documentation

Start at the [documentation index](docs/README.md). It links the getting-started guide, command cookbook, chain concepts, security notes, architecture, development/testing, and troubleshooting.

## References

- [Foundry Cast documentation](https://www.getfoundry.sh/cast/index.html)
- [Monad mainnet network information](https://docs.monad.xyz/developer-essentials/network-information)
- [Monad testnet network information](https://docs.monad.xyz/developer-essentials/testnets)
- [BNB Smart Chain JSON-RPC endpoints](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)
