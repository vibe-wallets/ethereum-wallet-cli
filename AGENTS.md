# Project instructions

- After each command the user runs, the wallet CLI must display exactly which
  underlying wrapper commands it executed. Show every Foundry invocation,
  including checks, simulations and sends, after the user command completes or
  fails. Send this trace to stderr so JSON stdout remains machine-readable.
  Commands handled locally should explicitly say no external command ran.
  Never display private keys or passphrases; redact RPC credentials in traces.
- Format source code before committing so it remains easy to read. Run the
  project's formatter and formatting check along with relevant tests before a commit.

- Proactively save meaningful progress to GitHub with coherent commits and pushes.
  Run relevant validation and inspect the diff before pushing, then check the CI
  results for the pushed commit. Investigate and fix meaningful failures; never
  report CI as passing while its result is pending or unknown.

- End-to-end validation must pull the published image and exercise both actual
  wallet launchers and commands inside their interactive shells, including wallet
  management, balances, native/ERC-20 transfers, signing and failure paths. A local
  build or wallet-creation smoke test alone does not prove registry delivery. CI
  must test registry pulls on a fresh runner before promoting default image tags.

## Scope and wallet isolation

- `ethereum-wallet-cli` defaults to Ethereum mainnet; `monad-wallet-cli` defaults to
  Monad mainnet. Each command has its own configuration folder and encrypted
  wallet store, and reads only its own environment prefix (`ETHEREUM_WALLET_*` or
  `MONAD_WALLET_*`).
- Each supported chain must have its own CLI command and configuration folder.
  Do not add generic cross-chain switching or require users to configure chain IDs.
  Network options select only mainnet, testnet or a local test node for that command.
- Delegate encryption, signing, ABI encoding and RPC work to Foundry Cast.
  Do not implement custom wallet cryptography or accept secret command arguments.
- Use only test wallets and isolated local Anvil instances for integration tests.
- Do not modify the copied Solana reference under `tmp/solana-wallet-cli/`.
- Keep `PLAN.md` consistent with implementation and validation state.
