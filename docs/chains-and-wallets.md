# Chain and wallet concepts

## An EVM address can exist on many chains

Ethereum, Monad, BNB Smart Chain, and many other EVM networks use the same address format and signing model. An address derived from one private key can therefore be the same on multiple EVM chains. The account's balance, transaction history, token contracts, and nonce are still chain-specific. A token address on Ethereum may refer to a different contract or no contract on another chain.

Before a transfer, verify both the selected chain and the destination. Never infer the chain from the address alone.

The Ethereum, Monad, and BNB Smart Chain launchers keep separate wallet stores. Creating a new wallet in each creates different private keys. To use one account across launchers, import the same private key separately into each store; each copy is encrypted with its own passphrase.

## Chain ID and RPC endpoint

The chain ID is part of signed Ethereum transactions and helps prevent replaying a transaction on a different chain. The RPC URL tells Cast where to send read and broadcast requests. Checking that an endpoint reports the expected chain ID catches some configuration errors, but the check does not authenticate the RPC operator or prove that returned data is correct.

Public RPC services can impose rate limits, change availability, log requests, or return misleading data. For valuable transactions, prefer a provider you trust, inspect the transaction summary, and independently verify the final hash on a trusted explorer or node.

## Supported networks and endpoints

Network selection is fixed by each launcher. `ethereum-wallet-cli` supports Ethereum mainnet, Sepolia, and local Anvil; `monad-wallet-cli` supports Monad mainnet, Monad Testnet, and local Anvil; `bsc-wallet-cli` supports BNB Smart Chain mainnet, BSC Testnet, and local Anvil. All three commands use the `--network` values `mainnet`, `testnet`, and `local`:

| Launcher | `--network` | Chain | Chain ID | Default RPC URL |
| --- | --- | --- | ---: | --- |
| Ethereum | `mainnet` | Ethereum | 1 | `https://ethereum-rpc.publicnode.com` |
| Ethereum | `testnet` | Sepolia | 11155111 | `https://ethereum-sepolia-rpc.publicnode.com` |
| Ethereum | `local` | Anvil | 31337 | `http://127.0.0.1:8545` |
| Monad | `mainnet` | Monad | 143 | `https://rpc.monad.xyz` |
| Monad | `testnet` | Monad Testnet | 10143 | `https://testnet-rpc.monad.xyz` |
| Monad | `local` | Anvil | 31337 | `http://127.0.0.1:8545` |
| BNB Smart Chain | `mainnet` | BNB Smart Chain | 56 | `https://bsc-rpc.publicnode.com` |
| BNB Smart Chain | `testnet` | BSC Testnet | 97 | `https://bsc-testnet-rpc.publicnode.com` |
| BNB Smart Chain | `local` | Anvil | 31337 | `http://127.0.0.1:8545` |

Each launcher starts on its own mainnet by default. Select `--network testnet` or `--network local` for a run or shell session. `chain list` and `chain info [mainnet|testnet|local]` are read-only and show the selected profile's supported networks. The selected network is not saved between invocations; each profile's supported networks are fixed by its entrypoint.

`--rpc-url URL` can override the endpoint for the selected network. The expected chain ID remains fixed; before an RPC operation the CLI checks that the endpoint reports that ID. This catches some configuration errors, but it does not authenticate the RPC provider. Public services may change or rate-limit requests.

The `local` endpoint is loopback from the CLI process. In Docker, `127.0.0.1` points inside the wallet container and reaches Anvil only when Anvil shares its network namespace. To reach a host Anvil process, supply a host-reachable endpoint with `--rpc-url` and Docker networking that exposes it.

The Ethereum launcher reads `ETHEREUM_WALLET_NETWORK`, `ETHEREUM_WALLET_RPC_URL`, `ETHEREUM_WALLET_CONFIG_DIR`, and `ETHEREUM_WALLET_IMAGE`. Monad reads `MONAD_WALLET_NETWORK`, `MONAD_WALLET_RPC_URL`, `MONAD_WALLET_CONFIG_DIR`, and `MONAD_WALLET_IMAGE`. BNB Smart Chain reads `BSC_WALLET_NETWORK`, `BSC_WALLET_RPC_URL`, `BSC_WALLET_CONFIG_DIR`, and `BSC_WALLET_IMAGE`. CLI options `--network`, `--rpc-url`, and `--config-dir` override the matching environment values. All launchers use `ghcr.io/vibe-wallets/ethereum-wallet-cli:main` by default and pull the selected remote image on each run. Use `ethereum-wallet-cli:local` only after `make build` and an explicit profile image override. The wrappers do not read host `.env` files automatically.

For an Anvil instance in another Docker container, optionally set `ETHEREUM_WALLET_DOCKER_NETWORK`, `MONAD_WALLET_DOCKER_NETWORK`, or `BSC_WALLET_DOCKER_NETWORK` to a user-created Docker network name. The launcher passes this value only as Docker's `--network` setting. The wallet process does not receive it as an environment variable. With no setting, Docker uses its default network. Use an RPC URL reachable by the wallet container, for example `http://anvil:8545`; container loopback `127.0.0.1` does not point to the host or another container.

## Named wallets and defaults

Wallet aliases make it possible to keep several encrypted keys in one local configuration directory. Each launcher has a different config directory. `wallet use ALIAS` selects a wallet for the current invocation or shell session. `wallet default ALIAS` saves that profile's default wallet and also selects it immediately. A newly created/imported wallet becomes active, and the first wallet becomes that profile's default. `wallet info [ALIAS]` displays public metadata for a wallet; `address` displays the active wallet's public address.

Wallet metadata is not secret. Private key material is stored only in Foundry's encrypted keystore files. The key must be unlocked through a hidden prompt when a signing command needs it.

## Amounts and token decimals

Native coin amounts are entered in whole currency units, such as `0.01` ETH or MON, with 18 decimal places. ERC-20 amounts are entered in token units. The CLI reads the contract's `decimals()` value before converting balance and transfer amounts; for example, an 18-decimal token uses 18 fractional places. The token symbol and decimals come from the contract and may be misleading or malicious. Review the contract address and transfer summary before confirming. Amount input is a nonnegative decimal string; exponent notation, commas, and negative values are rejected.

Avoid copying values through spreadsheets or tools that round large integers. JSON output may represent blockchain quantities as decimal or hexadecimal strings so clients can preserve their full precision.

## Chain references

For up-to-date chain IDs and official RPC details, consult [Monad mainnet network information](https://docs.monad.xyz/developer-essentials/network-information), [Monad testnet network information](https://docs.monad.xyz/developer-essentials/testnets), and the [BNB Smart Chain JSON-RPC endpoints](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/). Network parameters and public endpoints can change. The CLI's displayed built-in configuration is what this build will use. On BNB Smart Chain the base fee is pinned to 0 (BEP-226); the gas price is the real cost.
