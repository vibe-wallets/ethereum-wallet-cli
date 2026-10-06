# Ethereum and Monad Wallet CLIs — complete

Implemented: Foundry-backed `ethereum-wallet-cli` and `monad-wallet-cli` with
independent XDG config folders, environment prefixes and encrypted wallet stores.
Each command supports fixed mainnet/testnet/local network choices; no cross-chain
switching or user-configured chain IDs. Future chains require separate entrypoints.

Features: encrypted named wallets, interactive shell and one-shot JSON mode,
exact native/ERC20 amounts, chain-ID verification, transfer simulation/estimation,
confirmation, encrypted signing, validated receipts and pending transaction inspection.
Every user command prints underlying Cast invocations afterward on stderr; custom
RPC URLs are masked. AGENTS.md records this and pre-commit formatting requirements.

Docker image: `ethereum-wallet-cli:local` contains both entrypoints. Foundry 1.8.5
and Python 3.12 bases are digest-pinned. Launchers map host UID/GID, isolate config
mounts, and use read-only filesystems/capability restrictions. README and eight guides
cover onboarding, commands, networks, backup/restore, security, architecture and tests.

Final validation actually run:
- make format format-check lint test (Ruff 0.16.10): passed; 61 offline tests,
  with 4 opt-in cases skipped during ordinary offline discovery.
- make test-integration: passed inside Docker; 64 tests including 3 real local
  Foundry/Anvil scenarios; Docker-launcher E2E case skipped inside this container.
  Tests include wallet creation/import, encrypted native/ERC20 signing, wrong password,
  false-return token, dry-run nonce/balance invariants, receipts and chain mismatch.
- make test-docker: passed; both actual launchers create disposable encrypted wallets
  through PTYs, hide passwords, trace after output, select IDs 1/143, and isolate stores.
- Source lint, shell syntax, Markdown links/anchors and repository acceptance reviewed.

Implementation is complete. Saving the implementation and updated AGENTS.md to GitHub
is now authorized; commit/push and verification of the resulting CI are in progress.
No live-funded networks, system package installs or home-folder modifications.
Development tools were installed/extracted only below /tmp; the Solana reference is unchanged.
