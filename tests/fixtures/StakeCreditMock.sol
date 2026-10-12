// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// Minimal stand-in for a BSC StakeHub per-validator credit (share) contract.
///
/// `StakeHubMock.getValidatorCreditContract` points at this runtime, which the
/// Docker E2E installs at 0x3003 with `anvil_setCode`.
contract StakeCreditMock {
    mapping(address => uint256) public shares;
    mapping(address => uint256) public pooled;

    /// Mint shares and pool BNB for a delegator; only :contract:`StakeHubMock` calls this.
    function credit(address account, uint256 amount) external {
        shares[account] += amount;
        pooled[account] += amount;
    }

    function balanceOf(address account) external view returns (uint256) {
        return shares[account];
    }

    function getPooledBNB(address account) external view returns (uint256) {
        return pooled[account];
    }

    function getSharesByPooledBNB(uint256 amount) external pure returns (uint256) {
        return amount;
    }

    function pendingUnbondRequest(address) external pure returns (uint256) {
        return 1;
    }

    function claimableUnbondRequest(address) external pure returns (uint256) {
        return 0;
    }

    function totalPooledBNB() external view returns (uint256) {
        return address(this).balance;
    }
}
