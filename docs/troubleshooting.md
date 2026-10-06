# Troubleshooting

## `docker: command not found` or the daemon is unavailable

Install and start Docker, then verify `docker info` succeeds. Building and launching the image both require a working Docker daemon.

## The launcher says it cannot pull an image

The default local image `ethereum-wallet-cli:local` is not pulled. Build it with `make build`. If `ETHEREUM_WALLET_IMAGE` or `MONAD_WALLET_IMAGE` is set to a remote name, the corresponding launcher pulls that name on every run. Check the image name, network access, and registry access. The wrapper does not silently launch an old cached remote image after a failed pull.

## Permission denied for wallet files

Each launcher creates its own host config directory with mode `0700`, then runs the container using your host UID/GID. Check that the parent path is writable and that another user or process has not changed ownership. The Ethereum profile uses `ETHEREUM_WALLET_CONFIG_DIR` or its XDG default; Monad uses `MONAD_WALLET_CONFIG_DIR` or its separate XDG default.

## No RPC response, wrong chain, or rate limit

Inspect `chain info`, verify the selected network and RPC URL, and confirm that the endpoint is online and supports the required JSON-RPC methods. Public endpoints can be rate-limited. A fresh launch uses the selected wrapper's mainnet unless `--network` or its profile's network environment variable overrides it; network selection in one shell does not change the next launch. An endpoint reporting the expected chain ID is not proof that it is trustworthy.

## A send estimate fails

The node may reject simulation because the account lacks funds, the destination or token contract is invalid, contract execution would revert, or the RPC provider does not support a required method. Resolve the cause before retrying. A successful estimate still cannot guarantee later inclusion or execution.

## A transaction appears stuck

Use `tx inspect HASH` and check the transaction on a trusted explorer or RPC. If its receipt is still `null`, the CLI reports it as pending and includes the transaction data. Do not immediately repeat the payment. A delayed response can mean the first broadcast succeeded even if the CLI did not receive the response. Transactions may be pending, replaced, dropped, or reverted; consult the chain's transaction guidance before considering nonce replacement.

## Keystore password rejected

Check that the correct alias is selected and use the password associated with that encrypted keystore. The CLI cannot recover a lost keystore password. If you still have the original private key backup, import it as a new alias and store a new encrypted copy.

## JSON output or command syntax differs

Run either wrapper with `--help` for top-level options and `help` inside the shell. The same command parser is used by interactive commands and `-c 'COMMAND'`; use `--json` for machine-readable output. For automation, parse the successful result from standard output and keep standard error separate because it contains the Cast command trace and, on errors, the error record. Custom/local RPC URLs are masked in traces. Avoid depending on output fields not documented by the command or validated by your own parser.
