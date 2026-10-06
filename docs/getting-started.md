# Getting started

This guide uses Docker so the same pinned Foundry Cast tools run on different host systems. Install Docker Engine or Docker Desktop and GNU Make first. No Python package installation is needed for normal use.

## 1. Start the shell

The launchers pull the public image `ghcr.io/vibe-wallets/ethereum-wallet-cli:main` before every run, then start the matching command:

```bash
scripts/ethereum-wallet-cli
# Or open the separate Monad profile:
scripts/monad-wallet-cli
```

The image contains both CLI entrypoints. Ethereum and Monad use their own entrypoint, environment prefix, and wallet directory while sharing the same image. Public pulls require no registry login after a published tag is available. If the public tag is not available yet, use a local build explicitly:

```bash
make build
ETHEREUM_WALLET_IMAGE=ethereum-wallet-cli:local scripts/ethereum-wallet-cli
MONAD_WALLET_IMAGE=ethereum-wallet-cli:local scripts/monad-wallet-cli
```

Set `ETHEREUM_WALLET_IMAGE` or `MONAD_WALLET_IMAGE` to choose a different image for that profile. Remote images are pulled before every run; if that pull fails, the launcher stops instead of using a cached image.

`scripts/ethereum-wallet-cli` opens on Ethereum mainnet; `scripts/monad-wallet-cli` opens on Monad mainnet. They maintain separate wallets, aliases, network settings, and configuration. The default state directories are `~/.config/ethereum-wallet-cli` and `~/.config/monad-wallet-cli` (under `$XDG_CONFIG_HOME` when set). Override them with `ETHEREUM_WALLET_CONFIG_DIR` and `MONAD_WALLET_CONFIG_DIR`, respectively. Both wrappers create the host directory with mode `0700`, run the container with your host UID and GID, mount only that profile's state at `/data`, and use a read-only container filesystem apart from a temporary `/tmp`.

The network choices are fixed for each launcher: Ethereum `mainnet` (chain ID `1`), `testnet`/Sepolia (`11155111`), or local Anvil (`31337`); Monad `mainnet` (`143`), `testnet`/Monad Testnet (`10143`), or local Anvil (`31337`). Use `chain list` or `chain info` to inspect the endpoints for the current profile. Public endpoints can be rate-limited or change; confirm the selected network before sending.

For Anvil running in another Docker container, attach the wallet container to the same user-created Docker network with `ETHEREUM_WALLET_DOCKER_NETWORK` or `MONAD_WALLET_DOCKER_NETWORK`. Then use the Anvil container's network name as the RPC host, for example `--network local --rpc-url http://anvil:8545`. These Docker network variables only set Docker's `--network` option; they are not passed into the wallet. With no variable set, Docker's default network is used. The local endpoint `127.0.0.1:8545` works only when Anvil shares the wallet container's network namespace.

To use a testnet, start with `scripts/ethereum-wallet-cli --network testnet` or `scripts/monad-wallet-cli --network testnet`. `--network local` selects the built-in Anvil endpoint. `--rpc-url URL` overrides the RPC endpoint for that invocation, while the CLI keeps the selected network's fixed chain ID and checks it before RPC operations. Network choices apply to the current run or shell; a new launch starts on that entrypoint's mainnet unless its network environment variable is set.

## 2. Create a wallet

In the interactive shell, enter:

```text
wallet new daily
```

Follow Foundry's hidden prompt to enter a keystore password. Then select the wallet and display its public address:

```text
wallet use daily
wallet list
address
```

Foundry generates the private key and writes an encrypted keystore. The CLI does not export the generated raw key, so back up the full state directory and preserve its password separately. The keystore without its password cannot be used to sign.

The first wallet in a profile becomes its saved default automatically. `wallet use ALIAS` selects a wallet for the current shell; use `wallet default ALIAS` to save the wallet selected at later launches. The Monad launcher has its own wallet store. Run `scripts/monad-wallet-cli`, then create or import a wallet there; a wallet created independently in each profile will have a different address. To use the same key, import it separately into both profiles. Monad uses mainnet by default, so querying its balance does not require chain setup.

After setting up a wallet in the Monad profile, its mainnet balance needs no network configuration step:

```bash
scripts/monad-wallet-cli -c 'balance' --json
```

To import an existing private key instead, run `wallet import savings` and follow Foundry's hidden prompts. Do not paste private keys into shell commands, scripts, environment variables, tickets, or chat. This command imports a private key; it does not import a seed phrase or recover an HD wallet.

## Back up and restore wallet state

Exit the CLI, then copy the entire host state directory to secure backup storage. The copy must include both `config.json` and the `wallets/` directory so wallet aliases still point to their encrypted keystore files. Ethereum and Monad use separate stores: the defaults are `~/.config/ethereum-wallet-cli` and `~/.config/monad-wallet-cli`. If you set `ETHEREUM_WALLET_CONFIG_DIR` or `MONAD_WALLET_CONFIG_DIR`, back up that profile's selected directory instead. Keep each Foundry keystore password in a separate secure place. Do not put passwords alongside the encrypted backups.

To restore, copy the full directory back to a private host path and point the launcher at it:

```bash
ETHEREUM_WALLET_CONFIG_DIR=/secure/restore/ethereum-wallet scripts/ethereum-wallet-cli -c 'wallet list'
ETHEREUM_WALLET_CONFIG_DIR=/secure/restore/ethereum-wallet scripts/ethereum-wallet-cli -c 'wallet info daily'
MONAD_WALLET_CONFIG_DIR=/secure/restore/monad-wallet scripts/monad-wallet-cli -c 'wallet list'
```

This confirms the alias, encrypted file, and public address are readable. The CLI has no non-broadcast command to test a keystore password; signing prompts for it when sending. For imported keys, also preserve your original key backup independently. For keys created with `wallet new`, the encrypted keystore and its separate password are the available backup. Restore each profile into its matching config directory; one launcher's wallet list never includes the other launcher's wallets.

## 3. Check the network and balance

```text
chain list
chain info
address
balance
```

In a shell, run the launcher with `--network testnet` to select the profile's testnet for that session. `chain list` and `chain info [mainnet|testnet|local]` inspect supported networks; their configuration is fixed by the launcher. Consult [chain and wallet concepts](chains-and-wallets.md) before sending to a network you have not used before.

The address and balance commands are read-only. A wallet does not need to be unlocked to display its address or query a balance.

## 4. Send only after checking the destination and chain

Use a small test amount on a test network first. Before sending, the CLI estimates gas and shows the chain ID, selected wallet, destination, amount, and estimate. It requires confirmation unless you explicitly use `--yes`. You can run `--dry-run` to get the gas estimate without signing or submitting:

```text
send 0xRecipientAddress 0.001 --dry-run
send 0xRecipientAddress 0.001
```

The amount is in the selected chain's native currency (ETH on Ethereum, MON on Monad). Check the selected chain, destination, amount, and estimated gas units before approving a real transfer. Gas units are not the total fee; the fee also depends on gas pricing and execution.

`--yes` skips the CLI confirmation only. Foundry still asks for the selected keystore's password through a hidden prompt, and signing requires an interactive terminal.

For ERC-20 transfers, first verify the token contract address from a trusted source:

```text
token balance 0xTokenContract
token send 0xTokenContract 0xRecipientAddress 1.25 --dry-run
```

The token contract determines the token and its decimals. A token symbol or familiar name alone does not prove that a contract is legitimate.

For ERC-20 sends, the CLI simulates `transfer` before estimating gas, rejects an explicit `false` return value, and accepts a no-return token. Simulation does not guarantee a later transaction will succeed.

## 5. Use one-shot commands

The same command handlers work from a shell prompt or as one-shot commands. Examples from the host:

```bash
scripts/ethereum-wallet-cli -c 'address'
scripts/ethereum-wallet-cli -c 'balance' --json
scripts/ethereum-wallet-cli -c 'wallet list' --json
scripts/monad-wallet-cli -c 'balance' --json
```

The Ethereum wrapper forwards `ETHEREUM_WALLET_NETWORK` and `ETHEREUM_WALLET_RPC_URL`; the Monad wrapper forwards `MONAD_WALLET_NETWORK` and `MONAD_WALLET_RPC_URL`. CLI options `--network` and `--rpc-url` override the environment and mainnet default. Neither wrapper reads an `.env` file from your current directory. See [supported networks and endpoints](chains-and-wallets.md#supported-networks-and-endpoints) for the fixed mappings.
