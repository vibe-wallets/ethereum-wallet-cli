# Ethereum and Monad Wallet CLIs

`ethereum-wallet-cli` and `monad-wallet-cli` are small personal command-line wallets for Ethereum and Monad. Both use Foundry Cast for key creation/import, encrypted keystores, signing, RPC requests, and transaction handling. The Docker image packages the CLI with pinned Cast binaries; each wrapper has its own wallet store and fixed network choices.

This repository does not publish a container image. Build it locally, then use the launcher:

```bash
make build
scripts/ethereum-wallet-cli
# Or open the Monad-default CLI:
scripts/monad-wallet-cli
```

The build creates `ethereum-wallet-cli:local`. `scripts/ethereum-wallet-cli` opens the Ethereum-default shell; `scripts/monad-wallet-cli` opens the Monad-default shell. The two CLIs use separate state directories and do not share wallet aliases or encrypted keys. By default, Ethereum state lives in `~/.config/ethereum-wallet-cli` and Monad state in `~/.config/monad-wallet-cli` (under `$XDG_CONFIG_HOME` when set). Override them with `ETHEREUM_WALLET_CONFIG_DIR` and `MONAD_WALLET_CONFIG_DIR`, respectively. Each directory is mounted at `/data` inside its disposable container.

For a first wallet, enter these commands in the shell. Secret entry happens through Foundry's hidden prompts:

```text
wallet new daily
wallet list
wallet use daily
address
balance
```

To import an existing private key, use `wallet import savings`; the prompt accepts the key without putting it in shell history or the process argument list. Keep your original key backup independently. For a key created with `wallet new`, back up the active profile's full state directory and keep its keystore password separately; this CLI does not export the generated raw key.

To use the Monad CLI, run `scripts/monad-wallet-cli`, then create or import a wallet in that separate profile. A `wallet new` command in each profile creates different keys. To use one private key on both networks, import it separately into each profile.

Run a single command without opening the shell with `-c`; `--json` requests machine-readable output:

```bash
scripts/ethereum-wallet-cli -c 'wallet list' --json
scripts/ethereum-wallet-cli -c 'chain list' --json
scripts/monad-wallet-cli -c 'balance' --json
```

The Ethereum CLI starts on Ethereum mainnet, and the Monad CLI starts on Monad mainnet. Select Sepolia or Monad Testnet for one run with `scripts/ethereum-wallet-cli --network testnet` or `scripts/monad-wallet-cli --network testnet`. `--network local` selects local Anvil in either profile. `--rpc-url URL` can override the endpoint for the selected network; the CLI still checks the fixed chain ID before network operations. Network choice lasts for that invocation or interactive shell session.

Network mappings are fixed per entrypoint: Ethereum `mainnet` is chain `1`, `testnet` is Sepolia (`11155111`), and `local` is Anvil (`31337`); Monad `mainnet` is chain `143`, `testnet` is Monad Testnet (`10143`), and `local` is Anvil (`31337`). Run `chain list` or `chain info` to inspect the networks supported by the selected profile and their RPC endpoints.

## What it supports

- Create or import named wallets, list them, select a wallet for the session, choose a saved default, and inspect wallet metadata. Each entrypoint has its own wallet store.
- Choose mainnet, testnet, or local Anvil through each entrypoint's fixed network mapping.
- Read a native coin balance or an ERC-20 balance.
- Send native coin or an ERC-20 transfer, with a dry-run estimate or an explicit confirmation.
- Inspect transaction details by transaction hash.
- Use an interactive shell, direct argv commands, or one-shot `-c` commands; request JSON output with `--json`.

The tool does not implement its own cryptography, ABI encoder, or JSON-RPC client. It does not support seed phrases, hardware wallets, arbitrary contract transaction construction, swapping, bridging, staking, or smart-account flows.

## Commands

```text
wallet new ALIAS
wallet import ALIAS
wallet list
wallet use ALIAS
wallet default ALIAS
wallet info [ALIAS]
address [ALIAS]
chain list
chain info [mainnet|testnet|local]
balance [ADDRESS]
send DESTINATION AMOUNT [--dry-run | --yes]
token balance CONTRACT [ADDRESS]
token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]
tx inspect HASH
```

The top-level options are `-c 'COMMAND'` / `--command 'COMMAND'` for a one-shot command, `--network mainnet|testnet|local` to choose a profile-supported network, `--rpc-url URL` to override its RPC endpoint, `--json` for JSON output, `--config-dir PATH` for an explicit state directory, and `--version`. Direct command arguments are also supported; when no command is supplied, the CLI opens its interactive shell. JSON output is available for one-shot commands only. Fresh invocations default to the entrypoint's mainnet; a selected network applies to that invocation or shell only.

`wallet use ALIAS` selects the wallet for the current session; `wallet default ALIAS` stores the profile's saved wallet default. Wallet defaults are separate between the Ethereum and Monad profiles.

After each command succeeds or fails, the CLI prints the underlying Foundry Cast invocations to standard error, including chain checks, simulations, and sends. Local commands explicitly report when no external command ran. Custom and local RPC URLs are masked in the trace; bundled public endpoint URLs remain visible. Private keys and passphrases are never printed. With `--json`, standard output remains the JSON result; standard error may contain the trace or error details.

See [the command cookbook](docs/command-cookbook.md) for complete examples and [getting started](docs/getting-started.md) for the initial setup. Run either wrapper with `--help`, or use `help` inside the shell.

## Build, tests, and development

```bash
make build              # Build the local Docker image
make test               # Offline Python tests
make test-integration   # Build image and run isolated Anvil integration tests
make test-docker        # Test both actual launchers with disposable wallets
make lint               # Ruff, Python compile, and shell syntax checks
make format            # Format source and tests (Ruff)
make format-check      # Check Python formatting
make run ARGS='--help'  # Run the containerized CLI
make run-monad          # Launch the Monad CLI
```

Integration tests use a local Anvil node and test-only keys. They do not contact live networks or use real funds or existing personal wallets. See [developer and test notes](docs/development.md) and [architecture](docs/architecture.md).

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
