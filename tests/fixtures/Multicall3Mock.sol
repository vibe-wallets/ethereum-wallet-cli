// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// Minimal Multicall3 stand-in for the Docker E2E.
///
/// BSC mainnet and testnet have the canonical Multicall3 deployed, which the
/// wallet batches delegator-share reads through. Local Anvil nodes do not, so the
/// E2E installs this runtime at the canonical address with `anvil_setCode` to keep
/// the wallet on its normal batched read path.
contract Multicall3Mock {
    struct Call3 {
        address target;
        bool allowFailure;
        bytes callData;
    }

    struct Result {
        bool success;
        bytes returnData;
    }

    function aggregate3(Call3[] calldata calls) external payable returns (Result[] memory results) {
        results = new Result[](calls.length);
        for (uint256 index; index < calls.length; ++index) {
            (bool success, bytes memory returnData) = calls[index].target.call(calls[index].callData);
            if (!success && !calls[index].allowFailure) {
                assembly {
                    revert(add(returnData, 32), mload(returnData))
                }
            }
            results[index] = Result(success, returnData);
        }
    }
}
