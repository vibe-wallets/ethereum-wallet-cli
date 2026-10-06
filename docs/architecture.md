# Architecture

The project is intentionally a thin command interface over Foundry Cast. Cast supplies EVM key generation/import and encrypted keystores, transaction signing and sending, JSON-RPC calls, ABI-related token calls, and transaction inspection. The Python standard-library application handles aliases, local chain selection, prompt and command routing, input validation, and output formatting.

The Docker image is built from a small Python runtime and copies in pinned `cast` and `anvil` binaries from the Foundry v1.8.5 image. It runs `ethereum-wallet-cli` as an unprivileged user with `/data` as the configuration directory. The Monad wrapper selects the same image's `monad-wallet-cli` entrypoint. Each wrapper binds its own host configuration directory at `/data` and forwards only that profile's network and RPC environment variables, keeping wallet state separate.

## Data flow

For read operations, the CLI obtains the selected chain and RPC URL, then invokes Cast against that endpoint. Signing operations ask Cast to unlock a local encrypted keystore using a hidden password prompt. Cast signs and broadcasts the transaction; the CLI reports the resulting transaction hash or the error returned by Cast. The CLI does not implement custom cryptography or a separate transaction signer.

Each external invocation is recorded as shell-quoted argv and printed to standard error after the command result or error. If a command stays local, the wrapper prints `[wrapper] No external command ran (local command).` Custom and local RPC URLs are replaced with `<redacted-rpc-url>` in the trace; bundled public RPC endpoints remain visible. JSON result output stays on standard output.

The local configuration stores chain definitions, wallet aliases, and public addresses. Each alias points to a randomly named encrypted keystore in the `wallets/` directory. Ethereum and Monad use different config directories, so aliases and keys do not cross between entrypoints. Random filenames avoid making wallet aliases part of the keystore path; configuration itself is plaintext and should be protected.

## Extending EVM support

Network choices are fixed in each entrypoint. Adding support for another chain means adding a distinct CLI entrypoint and wrapper with its own config directory and environment prefix, then mapping its supported `mainnet`, `testnet`, and `local` choices to fixed chain IDs and default RPC URLs. Keep wallet, amount, RPC, and Cast integration logic in the shared backend. Update command tests, Docker integration coverage, and the network guide with the new profile. Chain support does not imply that every EVM protocol or token is safe or compatible, and the tool does not validate that a token contract is canonical. Future features should preserve exact integer amounts, avoid plaintext secret interfaces, and keep signing delegated to Foundry.

## Public command interface

The interactive shell and one-shot `-c` mode route through the same command parser. Direct arguments can run a command without `-c`, and `--json` requests structured output for one-shot commands. `ethereum-wallet-cli` maps `--network mainnet|testnet|local` to Ethereum, Sepolia, or Anvil; `monad-wallet-cli` maps those choices to Monad, Monad Testnet, or Anvil. Both default to their profile's mainnet. `chain list` and `chain info` inspect only the current profile's fixed mappings. The wallet/network workflows are described in the [command cookbook](command-cookbook.md); run either wrapper with `--help` for the exact top-level options.

Human rendering lives in `human.py`, focused help pages in `help.py`, and Tab-completion candidates in `completion.py`. The interactive shell wires `completion.py` into GNU readline and stores recent commands as plain text in the profile's config directory; `status`, `nonce`, and `gas` are read-only helpers over the same Cast RPC calls. Wallet rename and delete are local metadata operations that never touch on-chain funds.
