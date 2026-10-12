// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// Minimal stand-in for Monad's 0x1000 staking precompile.
///
/// The real staking system is a precompile with no deployed bytecode, so a plain
/// Anvil node cannot run it. The Docker E2E installs this runtime at 0x1000 with
/// `anvil_setCode` and seeds balances there, so the wallet's real `stake ...`
/// commands exercise encoding, estimation, signing, and receipts end to end.
contract MonadStakingMock {
    mapping(address => mapping(uint64 => uint256)) public stake;
    mapping(address => mapping(uint64 => uint256)) public rewards;

    function getEpoch() external pure returns (uint64, bool) {
        return (7, false);
    }

    function getExecutionValidatorSet(
        uint32
    ) external pure returns (bool, uint32, uint64[] memory) {
        uint64[] memory ids = new uint64[](3);
        ids[0] = 11;
        ids[1] = 22;
        ids[2] = 33;
        return (true, 0, ids);
    }

    /// The active set for the current epoch: the first two eligible validators.
    function getConsensusValidatorSet(
        uint32
    ) external pure returns (bool, uint32, uint64[] memory) {
        uint64[] memory ids = new uint64[](2);
        ids[0] = 11;
        ids[1] = 22;
        return (true, 0, ids);
    }

    /// One page of delegators, so `stake info --delegators` can be exercised.
    function getDelegators(
        uint64,
        address startDelegator
    ) external pure returns (bool, address, address[] memory) {
        address[] memory delegators = new address[](2);
        delegators[0] = address(0x0000000000000000000000000000000000000011);
        delegators[1] = address(0x0000000000000000000000000000000000000012);
        // Report the page as complete regardless of the cursor so tests stay simple.
        return (true, startDelegator, delegators);
    }

    function getValidator(
        uint64
    )
        external
        pure
        returns (
            address,
            uint64,
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            bytes memory,
            bytes memory
        )
    {
        return (
            address(0x00000000000000000000000000000000000000AA),
            0,
            1_000 ether,
            0,
            100_000_000_000_000_000, // 10%
            2 ether,
            1_000 ether,
            100_000_000_000_000_000,
            1_000 ether,
            100_000_000_000_000_000,
            hex"0102",
            hex"0304"
        );
    }

    function getDelegator(
        uint64 validatorId,
        address delegator
    ) external view returns (uint256, uint256, uint256, uint256, uint256, uint64, uint64) {
        return (stake[delegator][validatorId], 0, rewards[delegator][validatorId], 0, 0, 0, 0);
    }

    function getDelegations(
        address,
        uint64
    ) external pure returns (bool, uint64, uint64[] memory) {
        uint64[] memory ids = new uint64[](1);
        ids[0] = 11;
        return (true, 0, ids);
    }

    function delegate(uint64 validatorId) external payable {
        require(msg.value >= 1 gwei, "dust");
        stake[msg.sender][validatorId] += msg.value;
    }

    function undelegate(uint64 validatorId, uint256 amount, uint8) external returns (bool) {
        require(stake[msg.sender][validatorId] >= amount, "insufficient stake");
        stake[msg.sender][validatorId] -= amount;
        return true;
    }

    function withdraw(uint64, uint8) external pure returns (bool) {
        return true;
    }

    function claimRewards(uint64 validatorId) external returns (bool) {
        rewards[msg.sender][validatorId] = 0;
        return true;
    }

    function compound(uint64) external pure returns (bool) {
        return true;
    }
}
