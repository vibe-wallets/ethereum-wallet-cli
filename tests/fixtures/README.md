# Stateful ERC-20 E2E fixture

`TestToken.runtime.hex` is the deployed runtime for `TestToken.sol`, compiled
with the official Solidity 0.8.30 binary (`solc 0.8.30+commit.73712a01`). The
compiler binary SHA-256 was
`f3e987dc6ecebd4bd350c48edcbc320b46cf9e3109bd3fc3d88f1acaf4c428f7`, matching
the official release checksum. The compiler input, including optimizer and
metadata settings, is checked in as `TestToken.compiler-input.json`.

The source uses `balanceOf` as a mapping at storage slot 0. The E2E test installs
the runtime with Anvil's `anvil_setCode`, then seeds the test sender with
`anvil_setStorageAt`. Its `transfer` implementation checks the sender's balance
and updates both balances, so the test can verify the resulting state after a
real Cast-signed transaction.

To reproduce the runtime with the same compiler, run:

```sh
solc --version
solc --standard-json < tests/fixtures/TestToken.compiler-input.json > /tmp/test-token-output.json
python3 -c 'import json; d=json.load(open("/tmp/test-token-output.json")); print("0x" + d["contracts"]["TestToken.sol"]["TestToken"]["evm"]["deployedBytecode"]["object"])'
```

The runtime file's SHA-256 is
`81c779bb96acdbe61478935d422a137579ac8894a3b85bfa9069dc96de68e8eb`.
