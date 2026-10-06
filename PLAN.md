# Published-image delivery and complete Docker E2E

Problem: CI passed local-build tests but launchers used an unpublished
`ethereum-wallet-cli:local` default. Users without a local build could not launch.

Goal: default to the published GHCR image; CI must publish, pull the exact image on a
fresh runner, run full Ethereum/Monad shell and command flows, and only then promote
that image to the default `main` tag. Keep separate encrypted stores and fixed IDs.

Status: complete. The release pipeline is green and the default launchers pull the
promoted image.

Verified release
- Workflow run https://github.com/vibe-wallets/ethereum-wallet-cli/actions/runs/37526883717
  on `3f0c83ec57be971fb4c9d74fb2422bbfa6ffed06`: `test`, `publish`, `published-e2e`,
  `promote`, and `default-image-e2e` all succeeded.
- `ghcr.io/vibe-wallets/ethereum-wallet-cli:main` and `:latest` both point at digest
  `sha256:82396d33ac444478185bd4b9ed7f10f27cb8f8a4aae42db58f9f19953b698fd7`, the image
  the fresh-runner registry E2E validated.
- Both ordinary default launchers (`scripts/ethereum-wallet-cli`,
  `scripts/monad-wallet-cli`) pulled `:main` and returned correct `chain list` /
  `chain info` JSON with the wrapper trace on stderr.

Added after the release fix

- `clear` command: resets the interactive terminal; in one-shot JSON mode it returns
  `{"ok": true, "cleared": true}`. It is handled locally, so the trace reports that no
  external command ran.
- Pretty human output ported from the sibling Solana wallet CLI: section titles,
  aligned key/value rows, tables with a narrow-terminal fallback, real-fund network
  labels, styled help, and a styled interactive prompt/banner. ANSI color is used only
  on a TTY and is disabled by `NO_COLOR` or `TERM=dumb`, so JSON and piped output stay
  plain.
- Validation: 83 offline tests (the prior 69 plus 14 new in `tests/test_human.py`),
  `make test-integration`, and `make test-docker` all pass locally with the new output.

Distribution decision and delivery fix
- The GHCR package is distributed privately. The `publish` job publishes the immutable
  commit-SHA image; `published-e2e` and `default-image-e2e` grant `packages: read` to
  their runner token, configure a runner-temporary Docker credential, and pull the
  exact digest on a fresh runner before and after promotion. `promote` still updates
  `main`/`latest` only after the registry E2E passes; `default-image-e2e` re-tests the
  promoted tag.
- Root cause of the first failure: the Actions token cannot reliably change an
  organization package's visibility, and the delivery jobs had inherited only
  `contents: read`, so their authenticated pull lacked `packages` scope. The workflow
  now keeps an unauthenticated-availability report but no longer fails or promotes on
  anonymous access alone.
- Ordinary launchers use the caller's existing `ghcr.io` Docker credentials while the
  package is private. The `~/.docker/config.json` credential was verified to pull both
  the private SHA image and the promoted `:main` tag. Anonymous pulls still fail, as
  expected for a private package; a package-admin visibility change is documented in
  `docs/development.md` if anonymous public delivery is ever wanted.

Local validation actually run
- Ruff formatting, lint, `actionlint` 1.7.12, and the 69-test offline discovery passed
  (4 opt-in skips).
- `make test-published` against the private commit-SHA image passed the full
  actual-launcher Docker E2E in 25.085s, covering both interactive shells, wallet
  management, encrypted signing, native/ERC-20 transfers, balances, JSON output and
  failure paths.
- `git diff --check` passed; shell syntax checks passed for all launchers.

Constraints and notes
- No live funds; only test wallets and isolated local Anvil nodes. CI registry
  credentials live only in runner-temporary files; `GH_TOKEN` is never used for GHCR,
  and no `docker login` or home Docker configuration change was made.
- Runtime code and keystore behavior are unchanged by the delivery fix; the changes are
  confined to CI, launcher/docs accuracy, and this plan.
- Development tooling (Ruff, actionlint, PyYAML) was installed only under
  `/tmp/wallet-cli-dev`. Pushes used a temporary, API-verified GitHub known-hosts file.
- The token fixture uses checksum-verified solc 0.8.30 compilation; source/runtime and
  reproducible compiler input are checked in, so CI and tests need no compiler. All
  private keys are generated in test memory and are never checked in.
