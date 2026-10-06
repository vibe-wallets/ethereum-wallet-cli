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

Remaining: commit/push this coherent fix, monitor the publication workflow, run
the pulled-image E2E locally after release, and verify ordinary default launchers.

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
- Registry main-tag pull correctly fails today; no image has yet been published.

The token fixture uses checksum-verified solc 0.8.30 compilation; source/runtime
and reproducible compiler input are checked in, no compiler required by CI/tests.
All private keys are generated in test memory, never checked in. Only /tmp tooling
was downloaded (Ruff, actionlint, solc); no system installation or home writes.
