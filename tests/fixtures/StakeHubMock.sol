// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// Minimal stand-in for the BSC StakeHub system contract at 0x2002.
///
/// The Docker E2E installs this runtime at 0x2002 with `anvil_setCode`, so the
/// wallet's real `stake ...` commands exercise encoding, estimation, signing, and
/// receipts against an Anvil node with the BSC chain ID.
contract StakeHubMock {
    address public constant CREDIT = 0x0000000000000000000000000000000000003003;
    address public constant OPERATOR = 0x00000000000000000000000000000000000000bb;

    mapping(address => uint256) public delegated;

    struct Description {
        string moniker;
        string identity;
        string website;
        string details;
    }

    function unbondPeriod() external pure returns (uint256) {
        return 7 days;
    }

    function minSelfDelegationBNB() external pure returns (uint256) {
        return 2_000 ether;
    }

    function minDelegationBNBChange() external pure returns (uint256) {
        return 1 ether;
    }

    function maxElectedValidators() external pure returns (uint256) {
        return 45;
    }

    function getValidatorElectionInfo(
        uint256,
        uint256
    ) external pure returns (address[] memory, uint256[] memory, bytes[] memory, uint256) {
        address[] memory consensus = new address[](2);
        consensus[0] = address(0x00000000000000000000000000000000000000cc);
        consensus[1] = address(0x00000000000000000000000000000000000000dd);
        uint256[] memory powers = new uint256[](2);
        powers[0] = 1_000 ether;
        powers[1] = 2_000 ether;
        bytes[] memory votes = new bytes[](2);
        votes[0] = hex"01";
        votes[1] = hex"02";
        return (consensus, powers, votes, 2);
    }

    function consensusToOperator(address) external pure returns (address) {
        return OPERATOR;
    }

    function getValidatorCommission(
        address
    ) external pure returns (uint64, uint64, uint64) {
        return (900, 3_000, 700);
    }

    function getValidatorDescription(
        address
    ) external pure returns (Description memory) {
        return Description("Mock Validator", "mock", "https://example.invalid", "E2E fixture");
    }

    function getValidatorBasicInfo(address) external pure returns (uint256, bool, uint256) {
        return (1_700_000_000, false, 0);
    }

    function getValidatorCreditContract(address) external pure returns (address) {
        return CREDIT;
    }

    function delegate(address, bool) external payable {
        require(msg.value >= 1 ether, "min delegation");
        delegated[msg.sender] += msg.value;
    }

    function undelegate(address, uint256 shares) external pure {
        require(shares > 0, "shares");
    }

    function claim(address, uint256) external pure {}
}
