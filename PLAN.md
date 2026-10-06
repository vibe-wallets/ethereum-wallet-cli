# Published-image delivery and complete Docker E2E

Problem: CI passed local-build tests but launchers used an unpublished
`ethereum-wallet-cli:local` default. Users without a local build could not launch.

Goal: default to published GHCR images; CI must publish, pull the exact image on a
fresh runner, run full Ethereum/Monad shell and command flows, and only then promote
that image to the default `main` tag. Keep separate encrypted stores and fixed IDs.

Implemented and locally validated:
- Launcher GHCR default, optional per-profile Docker network for isolated test nodes.
- Complete real-launcher E2E, including local Anvil native/ERC20 signing, error paths,
  wallet management, interactive shell, JSON and state persistence/isolation.
- CI publishing and fresh-runner registry-pull gate; local/remote delivery verification.
- Updated onboarding/development docs and regression rules in AGENTS.md.

Committed/pushed delivery fix: 7fd5d6364b8fa0c832ed07bb7ebc7e52e9aa0c06.
Run https://github.com/vibe-wallets/ethereum-wallet-cli/actions/runs/37519302657:
- test and publish passed.
- published-e2e failed because GHCR created the package private; anonymous pull denied.
- promote and default-image-e2e skipped; main/latest were NOT published.
- The SHA image pulls with existing local Docker credentials and the full pulled-image
  E2E passed locally (25.017s), including both actual interactive wallet launchers.

Release workflow hardened for private distribution (decided; no automatic visibility
change): the `publish` job publishes the immutable SHA image; `published-e2e` and
`default-image-e2e` now grant `packages: read` to their runner token, configure a
temporary Docker credential, and pull the exact digest on a fresh runner before and
after promotion. The full Docker end-to-end suite, promote, and default-tag E2E gates
remain in place. The existing GHCR credential in `~/.docker/config.json` was verified
to pull the private SHA image; `:main` is unpublished until promotion runs. A manual
package-admin visibility change remains documented for anyone who later wants
anonymous public pulls.

Next: push this workflow fix, monitor the new run, and confirm publish, published-e2e,
promote, and default-image-e2e all pass before claiming release delivery. If the
GITHUB_TOKEN visibility call is rejected, the job fails closed and a package
administrator must set visibility Public as documented in docs/development.md.

Confirmed: previous workflow run37509627072 passed on a718fba, but only local image
builds and limited wallet-create/chain-info smoke coverage, not registry delivery.
No claim of published-image success until the pull/run gate passes.

Constraints: no live funds; use existing local Docker registry credentials, no docker
login or home config changes. CI registry credentials live only in runner temp files;
never use GH_TOKEN for GHCR. Runtime code/keystore behavior remains compatible.
Development Ruff installed in /tmp/wallet-cli-dev only; no system packages installed.

Local validation actually run:
- Ruff formatting, lint and 69-test offline discovery passed (4 opt-in skips).
- Docker-contained integration discovery passed (69 tests; Docker E2E skipped).
- Full actual-launcher Docker E2E passed for both profiles, including encrypted
  signing and exact native/stateful ERC20 balance deltas (18.23s).
- actionlint 1.7.12 and git diff --check passed.
- The immutable SHA image is published privately; the anonymous gate correctly failed.

The token fixture uses checksum-verified solc 0.8.30 compilation; source/runtime
and reproducible compiler input are checked in, no compiler required by CI/tests.
All private keys are generated in test memory, never checked in. Only /tmp tooling
was downloaded (Ruff, actionlint, solc); no system installation. SSH automatically
added GitHub to its default known_hosts on the first push; that file was not manually
read/edited/removed. Further pushes must use a temporary verified known-hosts file.
