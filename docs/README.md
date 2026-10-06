# Documentation

The Docker image has two launchers: `scripts/ethereum-wallet-cli` selects the Ethereum profile, and `scripts/monad-wallet-cli` selects the Monad profile. They use separate wallet/config directories and aliases. Each launcher exposes only its fixed mainnet, testnet, and local Anvil network choices.

Use these guides in order if you are new to the CLI:

1. [Getting started](getting-started.md) — launch from the public image or explicitly select a local build, then create or import a wallet and run your first read-only command.
2. [Chain and wallet concepts](chains-and-wallets.md) — understand named wallets, network selection, RPC endpoints, and EVM addresses.
3. [Command cookbook](command-cookbook.md) — copyable commands for balances, transfers, fixed network selection, and JSON automation.
4. [Security and operations](security.md) — protect backups, understand what the CLI and RPC can see, and handle transfers safely.

For contributors, read [architecture](architecture.md), [development and testing](development.md), then [troubleshooting](troubleshooting.md) when something fails.
