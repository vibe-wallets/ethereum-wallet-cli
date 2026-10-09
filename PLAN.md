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
- Readability pass across all Python modules, the shell launcher, the Makefile, and
  the Dockerfile: module and function docstrings, wrapped lines, grouped sections,
  and explanatory comments. No behavior change; the same validation passes.

Interactive usability and new commands

- Tab completion for commands, subcommands, networks, transfer flags, and wallet
  aliases, wired through GNU readline in the interactive shell, plus persisted
  command history and `history [COUNT]`.
- New read-only commands: `status` (network, wallet, native balance), `nonce
  [ADDRESS]`, and `gas`.
- New local wallet commands: `wallet rename OLD NEW` and `wallet delete ALIAS
  [--yes]`, which deregisters the alias and then removes the encrypted keystore;
  on-chain funds are never touched.
- Reworked `help [TOPIC]` into a sectioned index plus focused topics.
- Validation: 97 offline tests, `make test-integration`, and `make test-docker`
  (including a real-PTY tab-completion and new-command flow) all pass locally.

Advanced command batch

- Address book (`contact add/list/remove`), saved-token registry (`token
  add/list/remove/info`), read-only `call`, local `checksum`, `block`,
  `estimate`, ERC-20 `token allowance` and `token revoke`, local `tx
  list`/`tx watch`, and `wallet watch`/`wallet verify`.
- Config schema is now version 2 (adds contacts and saved tokens) with migration
  from version 1; a separate append-only `transactions.jsonl` records the hashes
  this CLI broadcasts, because EVM RPC endpoints cannot list history.
- Advanced commands are hidden from the default `help` index and from advanced-only
  `help TOPIC` pages; `help --verbose` or a `--verbose` session shows them.
- Validation: 108 offline tests, plus the Docker end-to-end suite extended with the
  new commands and verbose-help gating.

BNB Smart Chain profile

- Added `bsc-wallet-cli` as a third profile with the `BSC_WALLET_*` environment
  prefix and a `~/.config/bsc-wallet-cli` store: chains `bsc` (chain 56,
  `https://bsc-rpc.publicnode.com`) and `bsc-testnet` (chain 97,
  `https://bsc-testnet-rpc.publicnode.com`), plus the shared `local` Anvil (31337).
  The profile is named `bsc` everywhere to match the RPC/ecosystem convention.
- Config backfill: `_migrate_document` now injects any missing built-in chain
  entries on load while keeping schema version 2, so a config created before BSC
  existed (for example a shared Docker `/data`) can already select the new chains.
  The trace URL allowlist gained the two public BSC endpoints explicitly.
- BNB Smart Chain enables EIP-1559 with the base fee pinned to 0 (BEP-226), so the
  existing `gas` output shows a 0 base fee and the real cost is the gas price; the
  `gas` help topic now notes this.
- Verified against live endpoints: chain IDs 56/97, `cast base-fee` = 0, `cast
  estimate` (native 21000, BEP-20 34862), `cast call` on a BEP-20, and `cast mktx`
  producing a correctly signed type-2 transaction for chain 56.
- Validation: 113 offline tests, `make test-integration`, and `make test-docker`
  (three launchers and a third Anvil at chain 56) all pass locally.
- Provider extensibility: each chain currently pins one built-in RPC URL (PublicNode
  for Ethereum and BSC). Adding alternate or official providers later stays additive:
  extend the built-in chain definitions with extra URLs and evolve the config schema,
  while the shared `--rpc-url` / `*_WALLET_RPC_URL` override already selects a custom
  provider for a single run. No provider-selection command is implemented yet.

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
