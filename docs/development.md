# Development and testing

The application uses Python's standard library and targets Python 3.11 or newer. Docker is the normal runtime because it supplies pinned Foundry Cast and Anvil binaries. No Python dependencies are required to run the offline tests.

## Common commands

```bash
make help
make build
make test
make test-integration
make test-docker
make lint
make format-check
```

`make test` runs offline `unittest` coverage. It does not make public RPC requests. `make test-integration` runs opt-in integration tests using a local Anvil process/network and `WALLET_CLI_INTEGRATION`; it must not use a funded developer wallet or real funds. `make test-docker` drives both actual launchers through a terminal using disposable encrypted wallets, checking secret entry, output trace order, fixed network defaults, and separate stores. It does not contact public RPCs. The Docker end-to-end suite can also be selected with `WALLET_CLI_DOCKER_E2E=1` and an image path in `WALLET_CLI_DOCKER_E2E_IMAGE`. `make lint` runs Ruff linting, compiles Python modules, and checks both launchers' shell syntax.

Ruff is a development-only tool for linting and source formatting. Install the pinned developer tool and run the formatter and its check before submitting source changes:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
make format
make format-check
make lint
make test
deactivate
```

The test suite should cover command parsing, wallet and chain metadata, exact amount and address validation, JSON output, subprocess argument construction, storage behavior, and the container launcher. Integration tests verify the Cast-backed wallet and transfer paths against local Anvil only.

## Image and launcher

Build a local image with `make build`. It is tagged `ethereum-wallet-cli:local` by default; override with `make build IMAGE=example/name:tag`. `scripts/ethereum-wallet-cli` and `scripts/monad-wallet-cli` both use that image; the Monad launcher selects the Monad executable inside it. When `ETHEREUM_WALLET_IMAGE` or `MONAD_WALLET_IMAGE` names another image, its wrapper performs `docker pull` before starting it and stops if the pull fails.

`make run ARGS='--help'` launches the Ethereum profile; `make run-monad ARGS='--help'` launches Monad. Use `make run` or `scripts/ethereum-wallet-cli` for an Ethereum shell and `make run-monad` or `scripts/monad-wallet-cli` for a Monad shell. Each wrapper uses the host's UID/GID and its own private config directory; tests of the launchers use a fake Docker executable so they do not need a daemon.

## Adding another chain profile

Network support is selected through a dedicated executable and config profile. When adding another EVM network family:

1. Add a distinct CLI entrypoint and Docker launcher with its own config directory, environment prefix, and mainnet default.
2. Add fixed `mainnet`, `testnet`, and `local` mappings for that profile, with explicit chain IDs and documented RPC defaults. Do not add a user-supplied chain ID option or chain editor.
3. Reuse the shared wallet, amount, Cast, and shell code. Keep encryption and signing delegated to Foundry.
4. Add offline tests for network mappings and store isolation, local Anvil coverage for RPC/signing changes, and launcher coverage in `make test-docker`.
5. Update the README, chain guide, environment examples, architecture, and troubleshooting notes.

For other feature changes, keep external command invocations as argument arrays, never through a shell string. Never pass key material or passwords in argv or environment variables. Preserve a single source of truth for the fixed network mapping and wallet selection, and use string/integer arithmetic for coin values. No integration test should use public networks, a developer wallet, or live funds.

Foundry's upstream [Cast documentation](https://www.getfoundry.sh/cast/index.html) describes the underlying tool and versioned command behavior.
