# Development and testing

The application uses Python's standard library and targets Python 3.11 or newer. Docker is the normal runtime because it supplies pinned Foundry Cast and Anvil binaries. No Python dependencies are required to run the offline tests.

## Common commands

```bash
make help
make build
make test
make test-integration
make test-docker
make test-published PUBLISHED_IMAGE=ghcr.io/vibe-wallets/ethereum-wallet-cli:main
make lint
make format-check
```

`make test` runs offline `unittest` coverage and does not make public RPC requests. `make test-integration` runs the Cast wallet and transaction paths against an isolated local Anvil node. `make test-docker` builds the image and drives both actual Docker launchers against it with disposable encrypted wallets and local Anvil. The end-to-end coverage exercises interactive shells, wallet creation/import/list/use/default and store isolation, native balance and send, ERC-20 balance and fixture-backed transfer, signing prompts and transaction receipts, traces, JSON output, and expected failure paths. It does not use public RPCs or personal wallets. `make lint` runs Ruff linting, compiles Python modules, and checks both launchers' shell syntax.

`make test-published PUBLISHED_IMAGE=...` pulls the named registry image and runs the same Docker end-to-end suite against it. It does not build a local image, and it tests exactly the image reference supplied. CI publishes an immutable full-commit-SHA tag and uses its exact digest for the candidate check. A final fresh-runner check also tests the promoted default `main` tag.

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

Normal launcher use defaults to `ghcr.io/vibe-wallets/ethereum-wallet-cli:main`; every run pulls the selected remote image and fails if pulling fails. A public pull requires no login once the image has been published. Use `make build` for local development; it tags `ethereum-wallet-cli:local` by default. Local execution must opt into that tag explicitly, for example `make run IMAGE=ethereum-wallet-cli:local` or `ETHEREUM_WALLET_IMAGE=ethereum-wallet-cli:local scripts/ethereum-wallet-cli`. The Monad wrapper uses the same selected image and chooses its own entrypoint. Set `ETHEREUM_WALLET_IMAGE` or `MONAD_WALLET_IMAGE` to override the image per profile.

`make run ARGS='--help'` launches the Ethereum profile; `make run-monad ARGS='--help'` launches Monad using `IMAGE` as an explicit override. Each wrapper uses the host's UID/GID and its own private config directory. Unit tests use a fake Docker executable and do not need a daemon; the full `make test-docker` suite does.

If Anvil runs in a separate Docker container, put it on a user-created network and set `ETHEREUM_WALLET_DOCKER_NETWORK` or `MONAD_WALLET_DOCKER_NETWORK` to that network's name. Pass an RPC URL using the Anvil container name (such as `http://anvil:8545`). The launcher applies this variable only to Docker networking; it does not pass it to the wallet process. With the variable unset, Docker uses its default network.

## CI image release gates

The release sequence first builds and validates an image, then publishes that tested artifact under an immutable full-commit-SHA tag. A fresh anonymous runner pulls the exact digest of that SHA-tagged image and reruns the full Docker end-to-end suite, covering both profiles and wallet management, signing, native transfers, fixture-backed ERC-20 transfers, output, and error paths. Only after those checks pass does CI promote that exact image digest to the public `main` and `latest` tags. The moving `main` tag is updated only after the fresh-runner registry test succeeds; a final fresh-runner job pulls and tests the promoted default tag too. To test any published reference yourself, run `make test-published PUBLISHED_IMAGE=...`.

The public registry pull path works without authentication once the package is public. While the package is private, the same workflows pull it with the runner's temporary GitHub Actions token, and ordinary launchers use the caller's existing GHCR credentials. CI publication uses that token and a temporary Docker credential configuration on the runner; it does not write credentials into the repository or developer Docker configuration. This pipeline description does not establish that a tag is currently available; check the successful release workflow before relying on a published image.

## Adding another chain profile

Network support is selected through a dedicated executable and config profile. When adding another EVM network family:

1. Add a distinct CLI entrypoint and Docker launcher with its own config directory, environment prefix, and mainnet default.
2. Add fixed `mainnet`, `testnet`, and `local` mappings for that profile, with explicit chain IDs and documented RPC defaults. Do not add a user-supplied chain ID option or chain editor.
3. Reuse the shared wallet, amount, Cast, and shell code. Keep encryption and signing delegated to Foundry.
4. Add offline tests for network mappings and store isolation, local Anvil coverage for RPC/signing changes, and launcher coverage in `make test-docker`.
5. Update the README, chain guide, environment examples, architecture, and troubleshooting notes.

For other feature changes, keep external command invocations as argument arrays, never through a shell string. Never pass key material or passwords in argv or environment variables. Preserve a single source of truth for the fixed network mapping and wallet selection, and use string/integer arithmetic for coin values. No integration test should use public networks, a developer wallet, or live funds. Keep Python formatted with the repository's Ruff configuration and the shell launchers formatted with `shfmt -i 2 -ci -bn -sr`.

Foundry's upstream [Cast documentation](https://www.getfoundry.sh/cast/index.html) describes the underlying tool and versioned command behavior.

## First GHCR release: package visibility

The container package is distributed privately. GitHub can create a package as
private even when the linked repository is public, and repository access inheritance
does not by itself establish anonymous package access. This project does not try to
change that from CI: the Actions token can push images but does not reliably hold the
package-admin rights needed to change visibility, and the transition to public is not
reversible.

Instead, every fresh-runner registry gate authenticates with the runner's temporary
GitHub Actions token (`packages: read`), and ordinary launchers use the caller's
existing `ghcr.io` Docker credentials. `published-e2e` records whether the exact
digest happens to be anonymously readable, then performs the uncached pull and the
full Docker end-to-end suite. Only after that passes does `promote` publish `main`
and `latest`, and `default-image-e2e` re-tests the promoted tag on another fresh
runner. Do not bypass these gates to label an unreachable image as released.

If anonymous public delivery is ever wanted, a package administrator can open
[the package settings](https://github.com/orgs/vibe-wallets/packages/container/ethereum-wallet-cli/settings),
choose **Change visibility → Public**, confirm the package name, and re-run the
release. GitHub states that a public package cannot later become private; see its
[package visibility documentation](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).
