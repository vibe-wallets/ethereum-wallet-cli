# Docker E2E Solidity fixtures

All runtimes here are compiled with the official Solidity 0.8.30 binary
(`solc 0.8.30+commit.73712a01`). The compiler binary SHA-256 was
`f3e987dc6ecebd4bd350c48edcbc320b46cf9e3109bd3fc3d88f1acaf4c428f7`, matching
the official release checksum. Each `*.compiler-input.json` records the exact
optimizer and metadata settings, and each `*.runtime.hex` is the deployed
runtime, so CI and the tests need no compiler.

Reproduce any runtime with:

```sh
solc --version
solc --standard-json < tests/fixtures/<Name>.compiler-input.json > /tmp/output.json
python3 -c 'import json; d=json.load(open("/tmp/output.json")); print("0x" + d["contracts"]["<Name>.sol"]["<Name>"]["evm"]["deployedBytecode"]["object"])'
```

## TestToken

`TestToken.sol` is a small stateful ERC-20 used for balance and transfer tests.
Its `balanceOf` mapping is at storage slot 0: the E2E installs the runtime with
Anvil's `anvil_setCode` and seeds a balance with `anvil_setStorageAt`, then
verifies the resulting state after a real Cast-signed `transfer`.

The runtime file's SHA-256 is
`81c779bb96acdbe61478935d422a137579ac8894a3b85bfa9069dc96de68e8eb`.

## Staking mocks

Monad and BNB Smart Chain staking live in a precompile and a system contract
that a plain Anvil node cannot run. The Docker E2E installs these mocks with
`anvil_setCode` so the wallet's real `stake ...` commands exercise ABI encoding,
gas estimation, signing, receipts, and read decoding end to end:

- `MonadStakingMock.sol` is installed at `0x0000000000000000000000000000000000001000`
  (Monad's staking precompile). It implements the read views and the
  `delegate`/`undelegate`/`withdraw`/`claimRewards`/`compound` calls the wallet
  uses, and records delegate stake in a public mapping.
- `StakeHubMock.sol` is installed at `0x0000000000000000000000000000000000002002`
  (BSC's StakeHub). It implements the validator views and the
  `delegate`/`undelegate`/`claim` calls, and points at the credit mock below.
- `StakeCreditMock.sol` is installed at `0x0000000000000000000000000000000000003003`
  (a BSC per-validator credit/share contract).
- `Multicall3Mock.sol` is installed at the canonical Multicall3 address
  `0xcA11bde05977b3631167028862bE2a173976CA11`. BSC has the real Multicall3
  deployed, and the wallet batches delegator-share reads through it (`status`
  scans every validator's credit contract); local Anvil nodes do not, so the
  mock keeps the suite on the wallet's normal batched read path.

The E2E starts every Anvil node with `--network ethereum`, so the Monad node
reports chain ID 143 for the wallet's chain check while `0x1000` remains
ordinary code. Chain ID 56 (BSC) already uses the Ethereum family by default.
