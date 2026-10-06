# Security and operations

This CLI manages keys that can control on-chain assets. Treat wallet storage, passwords, RPC configuration, and transaction confirmation as security-sensitive.

## What is stored locally

Ethereum and Monad have separate host state directories. The defaults are `~/.config/ethereum-wallet-cli` and `~/.config/monad-wallet-cli`; each is under `$XDG_CONFIG_HOME` when that variable is set. Override the Ethereum path with `ETHEREUM_WALLET_CONFIG_DIR` and the Monad path with `MONAD_WALLET_CONFIG_DIR`. Each launcher creates its selected directory with mode `0700` and mounts it at `/data` in the container.

The directory contains `config.json` and the encrypted wallet keystores under `wallets/`. Files are written with restrictive permissions. Configuration includes aliases, addresses, and chain settings; it is not encrypted. Protect the entire directory and any backup because chain RPC URLs may contain provider credentials.

The CLI's `--config-dir PATH` option selects an explicit state directory and takes precedence over the profile's config environment variable when both are provided. The Docker wrappers use `ETHEREUM_WALLET_CONFIG_DIR` or `MONAD_WALLET_CONFIG_DIR` on the host to choose what they mount at `/data`.

The keystore is encrypted by Foundry. The password is needed to unlock it for signing. Back up the complete state directory, including `config.json` and `wallets/`, after closing the CLI so alias references and files stay together. Keep the password separately from the encrypted backup. For an imported key, also preserve the original key independently. For a key created with `wallet new`, this CLI does not export the generated raw private key, so the encrypted keystore and its password are the recovery copy. If that file is lost, or the password is lost, the wallet may be unrecoverable.

To check that a copied directory is readable, restore it to a separate private path and run `wallet list` and `wallet info ALIAS` with the matching profile's config variable set (`ETHEREUM_WALLET_CONFIG_DIR` or `MONAD_WALLET_CONFIG_DIR`). These commands check metadata and the encrypted keystore file; they do not validate the password. There is no non-broadcast signing check in the CLI. A wallet in one profile is not available in the other.

## Secret entry

Private keys and keystore passwords are not accepted as command-line options or environment variables. Creation and import use Foundry's hidden prompts. This helps avoid exposure through process listings, shell history, and container command logs. It does not protect against a compromised host, keylogger, malicious terminal, or untrusted build.

For visibility, the CLI reports the underlying Cast commands to standard error after each command, including chain checks, estimates, ERC-20 simulation, and transaction sends. Commands handled locally state that they made no external call. Custom and local RPC URLs are shown as `<redacted-rpc-url>` in traces; bundled public endpoint URLs remain visible. Private keys and passphrases are never shown. Review logs for public addresses, transaction details, built-in endpoint names, and local keystore paths before sharing them.

Do not put private keys, passwords, or provider API tokens in shell commands, scripts, `.env` files, support logs, screenshots, or version control. Restrict RPC endpoints containing API credentials as you would any secret.

## RPC and chain trust

Read requests reveal the queried address and request patterns to the RPC provider. Broadcast transactions also reveal signed transaction data and may be observed before confirmation. The provider can rate-limit requests, be unavailable, or return incorrect responses. Chain ID checks help detect a misconfigured endpoint but do not authenticate its operator.

Use a trusted RPC URL and verify the chain selection, destination, token contract, amount, and gas estimate before confirming. The CLI checks the configured RPC chain ID and estimates gas before sending; these checks do not authenticate the endpoint or guarantee execution. A gas estimate is a count of gas units; it is not a promise about the total fee in ETH/MON, which also depends on gas pricing and transaction execution. For large transfers, verify the resulting transaction independently using a trusted provider or explorer.

## Dry-runs and transaction retries

`--dry-run` asks the RPC node for an estimated gas amount; it does not sign or submit the transaction, calculate a guaranteed total fee, or guarantee that a later transaction will succeed. State can change and actual gas use or gas pricing can differ. The CLI does not automatically retry a broadcast. If a network error occurs after submission, first inspect the transaction hash and account nonce/status before sending again; retrying blindly can create a duplicate payment.

For ERC-20 sends, the CLI simulates `transfer` before estimating gas. It rejects a simulation that explicitly returns `false` and accepts a token method that returns no data. These checks lower the chance of submitting a call that reports failure, but a contract can still behave differently by state or during final execution.

Once submitted, the transaction cannot generally be cancelled by this CLI. A transaction may remain pending, be replaced by another transaction with the same nonce, or revert while still consuming gas.

## Container boundary and software trust

The Docker launcher runs as the caller's host UID/GID, drops Linux capabilities, enables `no-new-privileges`, uses a read-only container filesystem, and mounts only the wallet directory plus a temporary `/tmp`. This reduces the container's writable surface; it does not make a compromised image or host safe. The code and pinned Foundry image still need to be trusted.

This project is not audited and is intended for personal use. It does not provide hardware-wallet isolation, threshold signing, seed phrase management, or a guarantee that secrets are zeroized from process memory.
