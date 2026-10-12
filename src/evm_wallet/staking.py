"""Per-chain staking delegation built on Foundry Cast contract calls.

Staking is chain-specific: each supported network has a fixed system contract or
precompile with its own ABI and units. This module keeps one small backend per
chain behind a single ``stake ...`` command surface. All ABI encoding, estimation,
signing, and broadcasting is delegated to Cast; private keys never leave Foundry's
hidden keystore prompt.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

from .amounts import format_units, to_base_units, validate_address
from .errors import FoundryError, WalletCliError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .app import Application
    from .chains import Chain

# BNB Smart Chain exposes staking through the StakeHub system contract.
BSC_STAKE_HUB_ADDRESS = "0x0000000000000000000000000000000000002002"
# Monad exposes staking through the 0x1000 precompile.
MONAD_STAKING_ADDRESS = "0x0000000000000000000000000000000000001000"

MONAD_DUST_THRESHOLD_WEI = 1_000_000_000  # 1 gwei, per Monad staking API
MONAD_COMMISSION_BASE = 10**18
BSC_COMMISSION_BASE = 10_000
BSC_DEFAULT_LIMIT = 20
BSC_MAX_LIMIT = 45
MONAD_DEFAULT_LIMIT = 50

STAKING_USAGE = (
    "Usage: stake status [TARGET] | stake validators [--limit N] | stake info TARGET | "
    "stake delegate TARGET AMOUNT [--dry-run | --yes] | stake undelegate TARGET AMOUNT "
    "[--dry-run | --yes] | stake claim TARGET [--dry-run | --yes]. Monad also accepts "
    "stake withdraw VALIDATOR_ID WITHDRAW_ID and stake compound VALIDATOR_ID."
)


def _as_int(value: Any, label: str) -> int:
    """Parse a Cast integer result, which may be an int or a decimal string."""
    if isinstance(value, bool):
        raise FoundryError(f"Foundry returned an invalid {label} value.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            raise FoundryError(f"Foundry returned an invalid {label} value.") from None
    raise FoundryError(f"Foundry returned an invalid {label} value.")


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FoundryError(f"Foundry returned an invalid {label} value.")
    return value


def _percent(rate: int, base: int) -> str:
    """Render an integer rate scaled by ``base`` as a percentage with two decimals."""
    hundredths = rate * 10_000 // base
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _read(app: Application, chain: Chain, address: str, signature: str, *arguments: str) -> Any:
    """Call a read-only contract function and return the decoded JSON value."""
    output = app.cast.network(chain, ["call", address, signature, *arguments], json_output=True)
    return app._parse_json_result(output, "staking")


def _pop_option(tokens: list[str], name: str) -> tuple[str | None, list[str]]:
    """Remove ``--name VALUE`` or ``--name=VALUE`` and return the value and rest."""
    value: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == name:
            if index + 1 >= len(tokens):
                raise WalletCliError(f"Option {name} requires a value.")
            value = tokens[index + 1]
            index += 2
            continue
        if token.startswith(name + "="):
            value = token[len(name) + 1 :]
            index += 1
            continue
        remaining.append(token)
        index += 1
    return value, remaining


def _limit_option(tokens: list[str], *, default: int, maximum: int) -> tuple[int, list[str]]:
    raw, remaining = _pop_option(tokens, "--limit")
    if raw is None:
        return default, remaining
    try:
        limit = int(raw, 10)
    except ValueError:
        raise WalletCliError("--limit must be a positive integer.") from None
    if limit < 1:
        raise WalletCliError("--limit must be a positive integer.")
    return min(limit, maximum), remaining


def _run_transaction(
    app: Application,
    state: dict[str, Any],
    chain: Chain,
    *,
    command: str,
    title: str,
    to: str,
    signature: str,
    arguments: list[str],
    value_wei: int,
    preview: dict[str, str],
    record: dict[str, Any],
    dry_run: bool,
    yes: bool,
) -> dict[str, Any]:
    """Estimate, confirm, sign, and broadcast one staking contract call."""
    alias, metadata, keystore = app.wallet(state=state)
    if not dry_run:
        app.require_terminal(command)
        keystore = app.require_signing_wallet(alias, keystore, "stake")
    gas = app.estimate_contract_call(
        chain, to, signature, arguments, metadata["address"], value_wei
    )
    result: dict[str, Any] = {
        "command": command,
        "dry_run": dry_run,
        "chain": app.network_label(chain),
        "chain_id": chain.chain_id,
        "from_wallet": alias,
        "from": metadata["address"],
        "estimated_gas": gas,
        **preview,
    }
    if dry_run:
        return result
    if not yes:
        lines = [f"{title} on {app.network_label(chain)} (chain ID {chain.chain_id})?"]
        lines.extend(f"  {label}: {value}" for label, value in preview.items())
        lines.append(f"  estimated gas {gas}")
        lines.append("Type 'yes' to continue: ")
        if app.input_fn("\n".join(lines)).strip().lower() != "yes":
            raise WalletCliError("Transaction cancelled.")
    sys.stderr.write("Foundry will prompt for the selected keystore passphrase; input is hidden.\n")
    tx_result, tx_hash, receipt_status = app.broadcast_contract_call(
        chain, to, signature, arguments, metadata["address"], keystore, value_wei
    )
    if receipt_status == 0:
        raise WalletCliError(
            f"Staking transaction was mined with a failed status; transaction hash: {tx_hash}."
        )
    app.record_transaction(
        {
            "hash": tx_hash,
            "kind": command,
            "chain": chain.name,
            "chain_id": chain.chain_id,
            "from": metadata["address"],
            "timestamp": int(time.time()),
            **record,
        }
    )
    result.update(
        {
            "dry_run": False,
            "wallet": alias,
            "transaction": tx_result,
            "transaction_hash": tx_hash,
        }
    )
    return result


class _StakingBackend:
    """Shared dispatch for a chain's staking command surface."""

    chain_names: tuple[str, ...] = ()
    target_label = "target"
    address = ""

    def dispatch(
        self, app: Application, state: dict[str, Any], chain: Chain, action: str, tokens: list[str]
    ) -> dict[str, Any]:
        handlers = {
            "status": self.status_command,
            "validators": self.validators_command,
            "info": self.info_command,
            "delegate": self.delegate_command,
            "undelegate": self.undelegate_command,
            "claim": self.claim_command,
        }
        handler = handlers.get(action)
        if handler is None:
            raise WalletCliError(STAKING_USAGE)
        return handler(app, state, chain, tokens)

    def status_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    def validators_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    def info_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    def delegate_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    def undelegate_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    def claim_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(STAKING_USAGE)

    @staticmethod
    def _amount_arguments(tokens: list[str]) -> tuple[bool, bool, list[str]]:
        dry_run = "--dry-run" in tokens
        yes = "--yes" in tokens
        if dry_run and yes:
            raise WalletCliError("Choose either --dry-run or --yes, not both.")
        return dry_run, yes, [t for t in tokens if t not in {"--dry-run", "--yes"}]


class MonadStaking(_StakingBackend):
    """Monad staking precompile (0x1000): validator IDs and MON amounts."""

    chain_names = ("monad", "monad-testnet")
    target_label = "validator_id"
    address = MONAD_STAKING_ADDRESS

    _EPOCH = "getEpoch()(uint64,bool)"
    _VALSET = "getExecutionValidatorSet(uint32)(bool,uint32,uint64[])"
    _VALIDATOR = (
        "getValidator(uint64)(address,uint64,uint256,uint256,uint256,uint256,"
        "uint256,uint256,uint256,uint256,bytes,bytes)"
    )
    _DELEGATOR = (
        "getDelegator(uint64,address)(uint256,uint256,uint256,uint256,uint256,uint64,uint64)"
    )
    _DELEGATIONS = "getDelegations(address,uint64)(bool,uint64,uint64[])"

    @staticmethod
    def _validator_id(value: str) -> int:
        try:
            validator_id = int(value, 0)
        except ValueError:
            raise WalletCliError("Validator ID must be a nonnegative integer.") from None
        if validator_id < 0:
            raise WalletCliError("Validator ID must be a nonnegative integer.")
        return validator_id

    def _epoch(self, app: Application, chain: Chain) -> tuple[int, bool]:
        data = _as_list(_read(app, chain, self.address, self._EPOCH), "epoch")
        return _as_int(data[0], "epoch"), bool(data[1])

    def _validator(self, app: Application, chain: Chain, validator_id: int) -> dict[str, Any]:
        data = _as_list(
            _read(app, chain, self.address, self._VALIDATOR, str(validator_id)), "validator"
        )
        stake = _as_int(data[2], "stake")
        rewards = _as_int(data[5], "unclaimed rewards")
        return {
            "validator_id": validator_id,
            "auth_address": str(data[0]),
            "flags": _as_int(data[1], "flags"),
            "stake_wei": stake,
            "stake": format_units(stake, 18),
            "commission_rate": _as_int(data[4], "commission"),
            "commission": _percent(_as_int(data[4], "commission"), MONAD_COMMISSION_BASE),
            "unclaimed_rewards_wei": rewards,
            "unclaimed_rewards": format_units(rewards, 18),
            "consensus_stake": format_units(_as_int(data[6], "consensus stake"), 18),
            "consensus_commission": _percent(
                _as_int(data[7], "consensus commission"), MONAD_COMMISSION_BASE
            ),
            "snapshot_stake": format_units(_as_int(data[8], "snapshot stake"), 18),
            "snapshot_commission": _percent(
                _as_int(data[9], "snapshot commission"), MONAD_COMMISSION_BASE
            ),
            "secp_pubkey": str(data[10]),
            "bls_pubkey": str(data[11]),
        }

    def _delegations(self, app: Application, chain: Chain, address: str) -> list[dict[str, Any]]:
        validator_ids: list[int] = []
        start = 0
        while True:
            data = _as_list(
                _read(app, chain, self.address, self._DELEGATIONS, address, str(start)),
                "delegations",
            )
            done = bool(data[0])
            next_id = _as_int(data[1], "next validator id")
            ids = [_as_int(item, "validator id") for item in _as_list(data[2], "validator ids")]
            validator_ids.extend(ids)
            if done or not ids or next_id <= start:
                break
            start = next_id
        return [
            self._delegator(app, chain, validator_id, address) for validator_id in validator_ids
        ]

    def _delegator(
        self, app: Application, chain: Chain, validator_id: int, address: str
    ) -> dict[str, Any]:
        data = _as_list(
            _read(app, chain, self.address, self._DELEGATOR, str(validator_id), address),
            "delegator",
        )
        stake = _as_int(data[0], "stake")
        rewards = _as_int(data[2], "unclaimed rewards")
        return {
            "validator_id": validator_id,
            "stake_wei": stake,
            "stake": format_units(stake, 18),
            "unclaimed_rewards_wei": rewards,
            "unclaimed_rewards": format_units(rewards, 18),
            "pending_stake": format_units(_as_int(data[3], "pending stake"), 18),
            "next_pending_stake": format_units(_as_int(data[4], "next pending stake"), 18),
            "pending_epoch": _as_int(data[5], "pending epoch"),
            "next_pending_epoch": _as_int(data[6], "next pending epoch"),
        }

    def status_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) > 1:
            raise WalletCliError("Usage: stake status [VALIDATOR_ID].")
        epoch, in_delay = self._epoch(app, chain)
        _, metadata, _ = app.wallet(state=state)
        address = metadata["address"]
        if tokens:
            delegations = [self._delegator(app, chain, self._validator_id(tokens[0]), address)]
        else:
            delegations = self._delegations(app, chain, address)
        return {
            "command": "stake status",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "address": address,
            "epoch": epoch,
            "in_epoch_delay": in_delay,
            "dust_threshold": f"{format_units(MONAD_DUST_THRESHOLD_WEI, 18)} MON",
            "withdrawal_delay_epochs": 1,
            "delegations": delegations,
        }

    def validators_command(self, app, state, chain, tokens) -> dict[str, Any]:
        limit, remaining = _limit_option(tokens, default=MONAD_DEFAULT_LIMIT, maximum=500)
        if remaining:
            raise WalletCliError(STAKING_USAGE)
        validators: list[dict[str, Any]] = []
        start = 0
        while len(validators) < limit:
            data = _as_list(
                _read(app, chain, self.address, self._VALSET, str(start)), "validator set"
            )
            done = bool(data[0])
            next_index = _as_int(data[1], "next index")
            ids = [_as_int(item, "validator id") for item in _as_list(data[2], "validator ids")]
            for validator_id in ids:
                if len(validators) >= limit:
                    break
                validators.append(self._validator(app, chain, validator_id))
            if done or not ids or next_index <= start:
                break
            start = next_index
        return {
            "command": "stake validators",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "limit": limit,
            "validators": validators,
        }

    def info_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) != 1:
            raise WalletCliError("Usage: stake info VALIDATOR_ID.")
        info = self._validator(app, chain, self._validator_id(tokens[0]))
        return {
            "command": "stake info",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            **info,
        }

    def delegate_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 2:
            raise WalletCliError("Usage: stake delegate VALIDATOR_ID AMOUNT [--dry-run | --yes].")
        validator_id = self._validator_id(args[0])
        raw = to_base_units(args[1], 18)
        if raw < MONAD_DUST_THRESHOLD_WEI:
            raise WalletCliError("Monad delegations must be at least 0.000000001 MON (1 gwei).")
        amount = format_units(raw, 18)
        return _run_transaction(
            app,
            state,
            chain,
            command="stake delegate",
            title=f"Delegate {amount} MON to validator {validator_id}",
            to=self.address,
            signature="delegate(uint64)",
            arguments=[str(validator_id)],
            value_wei=raw,
            preview={"validator_id": str(validator_id), "amount": f"{amount} MON"},
            record={"validator_id": validator_id, "amount": amount, "amount_base_units": str(raw)},
            dry_run=dry_run,
            yes=yes,
        )

    def undelegate_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        withdraw_raw, args = _pop_option(args, "--withdraw-id")
        if len(args) != 2:
            raise WalletCliError(
                "Usage: stake undelegate VALIDATOR_ID AMOUNT [--withdraw-id N] [--dry-run | --yes]."
            )
        validator_id = self._validator_id(args[0])
        raw = to_base_units(args[1], 18)
        withdraw_id = 0
        if withdraw_raw is not None:
            try:
                withdraw_id = int(withdraw_raw, 10)
            except ValueError:
                raise WalletCliError("--withdraw-id must be between 0 and 255.") from None
        if not 0 <= withdraw_id <= 255:
            raise WalletCliError("--withdraw-id must be between 0 and 255.")
        amount = format_units(raw, 18)
        return _run_transaction(
            app,
            state,
            chain,
            command="stake undelegate",
            title=f"Undelegate {amount} MON from validator {validator_id}",
            to=self.address,
            signature="undelegate(uint64,uint256,uint8)",
            arguments=[str(validator_id), str(raw), str(withdraw_id)],
            value_wei=0,
            preview={
                "validator_id": str(validator_id),
                "amount": f"{amount} MON",
                "withdraw_id": str(withdraw_id),
            },
            record={
                "validator_id": validator_id,
                "amount": amount,
                "amount_base_units": str(raw),
                "withdraw_id": withdraw_id,
            },
            dry_run=dry_run,
            yes=yes,
        )

    def claim_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 1:
            raise WalletCliError("Usage: stake claim VALIDATOR_ID [--dry-run | --yes].")
        validator_id = self._validator_id(args[0])
        return _run_transaction(
            app,
            state,
            chain,
            command="stake claim",
            title=f"Claim rewards from validator {validator_id}",
            to=self.address,
            signature="claimRewards(uint64)",
            arguments=[str(validator_id)],
            value_wei=0,
            preview={"validator_id": str(validator_id)},
            record={"validator_id": validator_id},
            dry_run=dry_run,
            yes=yes,
        )

    def withdraw_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 2:
            raise WalletCliError(
                "Usage: stake withdraw VALIDATOR_ID WITHDRAW_ID [--dry-run | --yes]."
            )
        validator_id = self._validator_id(args[0])
        try:
            withdraw_id = int(args[1], 10)
        except ValueError:
            raise WalletCliError("Withdraw ID must be between 0 and 255.") from None
        if not 0 <= withdraw_id <= 255:
            raise WalletCliError("Withdraw ID must be between 0 and 255.")
        return _run_transaction(
            app,
            state,
            chain,
            command="stake withdraw",
            title=f"Withdraw validator {validator_id} request {withdraw_id}",
            to=self.address,
            signature="withdraw(uint64,uint8)",
            arguments=[str(validator_id), str(withdraw_id)],
            value_wei=0,
            preview={"validator_id": str(validator_id), "withdraw_id": str(withdraw_id)},
            record={"validator_id": validator_id, "withdraw_id": withdraw_id},
            dry_run=dry_run,
            yes=yes,
        )

    def compound_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 1:
            raise WalletCliError("Usage: stake compound VALIDATOR_ID [--dry-run | --yes].")
        validator_id = self._validator_id(args[0])
        return _run_transaction(
            app,
            state,
            chain,
            command="stake compound",
            title=f"Compound rewards for validator {validator_id}",
            to=self.address,
            signature="compound(uint64)",
            arguments=[str(validator_id)],
            value_wei=0,
            preview={"validator_id": str(validator_id)},
            record={"validator_id": validator_id},
            dry_run=dry_run,
            yes=yes,
        )

    def dispatch(self, app, state, chain, action, tokens) -> dict[str, Any]:
        if action == "withdraw":
            return self.withdraw_command(app, state, chain, tokens)
        if action == "compound":
            return self.compound_command(app, state, chain, tokens)
        return super().dispatch(app, state, chain, action, tokens)


class BscStaking(_StakingBackend):
    """BNB Smart Chain StakeHub (0x2002): operator addresses and share tokens."""

    chain_names = ("bsc", "bsc-testnet")
    target_label = "operator"
    address = BSC_STAKE_HUB_ADDRESS

    _UNBOND = "unbondPeriod()(uint256)"
    _MIN_SELF = "minSelfDelegationBNB()(uint256)"
    _MIN_CHANGE = "minDelegationBNBChange()(uint256)"
    _MAX_ELECTED = "maxElectedValidators()(uint256)"
    _ELECTION = "getValidatorElectionInfo(uint256,uint256)(address[],uint256[],bytes[],uint256)"
    _CONSENSUS_TO_OPERATOR = "consensusToOperator(address)(address)"
    _COMMISSION = "getValidatorCommission(address)((uint64,uint64,uint64))"
    _DESCRIPTION = "getValidatorDescription(address)((string,string,string,string))"
    _BASIC = "getValidatorBasicInfo(address)(uint256,bool,uint256)"
    _CREDIT = "getValidatorCreditContract(address)(address)"

    def _commission_rate(self, app: Application, chain: Chain, operator: str) -> int:
        data = _as_list(_read(app, chain, self.address, self._COMMISSION, operator), "commission")
        return _as_int(_as_list(data[0], "commission rate")[0], "commission rate")

    def _description(self, app: Application, chain: Chain, operator: str) -> dict[str, str]:
        data = _as_list(
            _read(app, chain, self.address, self._DESCRIPTION, operator), "description"
        )[0]
        fields = _as_list(data, "description")
        return {
            "moniker": str(fields[0]),
            "identity": str(fields[1]),
            "website": str(fields[2]),
            "details": str(fields[3]),
        }

    def _basic(self, app: Application, chain: Chain, operator: str) -> dict[str, Any]:
        data = _as_list(_read(app, chain, self.address, self._BASIC, operator), "validator info")
        return {
            "created_time": _as_int(data[0], "created time"),
            "jailed": bool(data[1]),
            "jail_until": _as_int(data[2], "jail until"),
        }

    def _credit_contract(self, app: Application, chain: Chain, operator: str) -> str:
        data = _as_list(_read(app, chain, self.address, self._CREDIT, operator), "credit contract")
        return validate_address(str(data[0]), "credit contract")

    def _parameters(self, app: Application, chain: Chain) -> dict[str, Any]:
        unbond = _as_int(
            _as_list(_read(app, chain, self.address, self._UNBOND), "unbond period")[0],
            "unbond period",
        )
        return {
            "unbond_period_seconds": unbond,
            "min_self_delegation": format_units(
                _as_int(
                    _as_list(
                        _read(app, chain, self.address, self._MIN_SELF), "min self delegation"
                    )[0],
                    "min self delegation",
                ),
                18,
            ),
            "min_delegation_change": format_units(
                _as_int(
                    _as_list(
                        _read(app, chain, self.address, self._MIN_CHANGE), "min delegation change"
                    )[0],
                    "min delegation change",
                ),
                18,
            ),
            "max_elected_validators": _as_int(
                _as_list(
                    _read(app, chain, self.address, self._MAX_ELECTED), "max elected validators"
                )[0],
                "max elected validators",
            ),
        }

    def status_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) > 1:
            raise WalletCliError("Usage: stake status [OPERATOR].")
        _, metadata, _ = app.wallet(state=state)
        address = metadata["address"]
        parameters = self._parameters(app, chain)
        if not tokens:
            return {
                "command": "stake status",
                "chain": app.network_label(chain),
                "chain_id": chain.chain_id,
                "address": address,
                "parameters": parameters,
                "delegation": None,
            }
        operator = validate_address(tokens[0], "operator address")
        credit = self._credit_contract(app, chain, operator)
        shares = _as_int(
            _as_list(_read(app, chain, credit, "balanceOf(address)(uint256)", address), "shares")[
                0
            ],
            "shares",
        )
        pooled = _as_int(
            _as_list(
                _read(app, chain, credit, "getPooledBNB(address)(uint256)", address), "balance"
            )[0],
            "balance",
        )
        rate = self._commission_rate(app, chain, operator)
        return {
            "command": "stake status",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "address": address,
            "parameters": parameters,
            "delegation": {
                "operator": operator,
                "credit_contract": credit,
                "shares": str(shares),
                "pooled_bnb_wei": pooled,
                "pooled_bnb": format_units(pooled, 18),
                "commission": _percent(rate, BSC_COMMISSION_BASE),
                "pending_unbond_requests": _as_int(
                    _as_list(
                        _read(
                            app,
                            chain,
                            credit,
                            "pendingUnbondRequest(address)(uint256)",
                            address,
                        ),
                        "pending unbond requests",
                    )[0],
                    "pending unbond requests",
                ),
                "claimable_unbond_requests": _as_int(
                    _as_list(
                        _read(
                            app,
                            chain,
                            credit,
                            "claimableUnbondRequest(address)(uint256)",
                            address,
                        ),
                        "claimable unbond requests",
                    )[0],
                    "claimable unbond requests",
                ),
            },
        }

    def validators_command(self, app, state, chain, tokens) -> dict[str, Any]:
        limit, remaining = _limit_option(tokens, default=BSC_DEFAULT_LIMIT, maximum=BSC_MAX_LIMIT)
        if remaining:
            raise WalletCliError(STAKING_USAGE)
        data = _as_list(
            _read(app, chain, self.address, self._ELECTION, "0", str(limit)), "election"
        )
        consensus = [str(item) for item in _as_list(data[0], "consensus addresses")]
        powers = [_as_int(item, "voting power") for item in _as_list(data[1], "voting powers")]
        validators: list[dict[str, Any]] = []
        for address, power in zip(consensus, powers):
            operator_data = _as_list(
                _read(app, chain, self.address, self._CONSENSUS_TO_OPERATOR, address),
                "operator",
            )
            operator = validate_address(str(operator_data[0]), "operator address")
            rate = self._commission_rate(app, chain, operator)
            validators.append(
                {
                    "operator": operator,
                    "consensus": address,
                    "stake_wei": power,
                    "stake": format_units(power, 18),
                    "commission": _percent(rate, BSC_COMMISSION_BASE),
                }
            )
        return {
            "command": "stake validators",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "limit": limit,
            "validators": validators,
        }

    def info_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) != 1:
            raise WalletCliError("Usage: stake info OPERATOR_ADDRESS.")
        operator = validate_address(tokens[0], "operator address")
        credit = self._credit_contract(app, chain, operator)
        total_pooled = _as_int(
            _as_list(_read(app, chain, credit, "totalPooledBNB()(uint256)"), "total pooled")[0],
            "total pooled",
        )
        return {
            "command": "stake info",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "operator": operator,
            "credit_contract": credit,
            "total_pooled_bnb_wei": total_pooled,
            "total_pooled_bnb": format_units(total_pooled, 18),
            **self._basic(app, chain, operator),
            "commission_rate": _percent(
                self._commission_rate(app, chain, operator), BSC_COMMISSION_BASE
            ),
            **self._description(app, chain, operator),
        }

    def delegate_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        vote_power = "--no-vote-power" not in args
        args = [token for token in args if token != "--no-vote-power"]
        if len(args) != 2:
            raise WalletCliError(
                "Usage: stake delegate OPERATOR_ADDRESS AMOUNT [--no-vote-power] "
                "[--dry-run | --yes]."
            )
        operator = validate_address(args[0], "operator address")
        raw = to_base_units(args[1], 18)
        minimum = _as_int(
            _as_list(_read(app, chain, self.address, self._MIN_CHANGE), "min delegation change")[0],
            "min delegation change",
        )
        if raw < minimum:
            raise WalletCliError(
                f"BNB Smart Chain delegations must be at least {format_units(minimum, 18)} BNB."
            )
        amount = format_units(raw, 18)
        return _run_transaction(
            app,
            state,
            chain,
            command="stake delegate",
            title=f"Delegate {amount} BNB to {operator}",
            to=self.address,
            signature="delegate(address,bool)",
            arguments=[operator, "true" if vote_power else "false"],
            value_wei=raw,
            preview={"operator": operator, "amount": f"{amount} BNB"},
            record={"operator": operator, "amount": amount, "amount_base_units": str(raw)},
            dry_run=dry_run,
            yes=yes,
        )

    def undelegate_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        shares_only = "--shares" in args
        args = [token for token in args if token != "--shares"]
        if len(args) != 2:
            raise WalletCliError(
                "Usage: stake undelegate OPERATOR_ADDRESS AMOUNT [--shares] [--dry-run | --yes]."
            )
        operator = validate_address(args[0], "operator address")
        if shares_only:
            try:
                shares = int(args[1], 10)
            except ValueError:
                raise WalletCliError("Shares must be a nonnegative integer.") from None
            if shares <= 0:
                raise WalletCliError("Shares must be greater than zero.")
            amount = format_units(shares, 18)
            preview_amount = f"{amount} BNB-equivalent"
        else:
            raw = to_base_units(args[1], 18)
            credit = self._credit_contract(app, chain, operator)
            shares = _as_int(
                _as_list(
                    _read(app, chain, credit, "getSharesByPooledBNB(uint256)(uint256)", str(raw)),
                    "shares",
                )[0],
                "shares",
            )
            if shares <= 0:
                raise WalletCliError("That BNB amount is too small to undelegate.")
            amount = format_units(raw, 18)
            preview_amount = f"{amount} BNB"
        return _run_transaction(
            app,
            state,
            chain,
            command="stake undelegate",
            title=f"Undelegate from {operator}",
            to=self.address,
            signature="undelegate(address,uint256)",
            arguments=[operator, str(shares)],
            value_wei=0,
            preview={"operator": operator, "amount": preview_amount, "shares": str(shares)},
            record={"operator": operator, "amount": amount, "shares": str(shares)},
            dry_run=dry_run,
            yes=yes,
        )

    def claim_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) not in {1, 2}:
            raise WalletCliError(
                "Usage: stake claim OPERATOR_ADDRESS [REQUEST_NUMBER] [--dry-run | --yes]."
            )
        operator = validate_address(args[0], "operator address")
        request_number = 0
        if len(args) == 2:
            try:
                request_number = int(args[1], 10)
            except ValueError:
                raise WalletCliError("Request number must be a nonnegative integer.") from None
            if request_number < 0:
                raise WalletCliError("Request number must be a nonnegative integer.")
        label = "all requests" if request_number == 0 else f"request {request_number}"
        return _run_transaction(
            app,
            state,
            chain,
            command="stake claim",
            title=f"Claim {label} from {operator}",
            to=self.address,
            signature="claim(address,uint256)",
            arguments=[operator, str(request_number)],
            value_wei=0,
            preview={"operator": operator, "request_number": str(request_number)},
            record={"operator": operator, "request_number": request_number},
            dry_run=dry_run,
            yes=yes,
        )


_BACKENDS: dict[str, _StakingBackend] = {}
for _backend in (MonadStaking(), BscStaking()):
    for _name in _backend.chain_names:
        _BACKENDS[_name] = _backend


def staking_supported(chain_name: str) -> bool:
    """Return whether a chain has a staking backend in this build."""
    return chain_name in _BACKENDS


def handle_stake(app: Application, tokens: list[str]) -> dict[str, Any]:
    """Dispatch a ``stake ...`` command to the backend for the active chain."""
    if len(tokens) < 2:
        raise WalletCliError(STAKING_USAGE)
    state = app.config()
    chain = app.active_chain(state)
    backend = _BACKENDS.get(chain.name)
    if backend is None:
        raise WalletCliError(
            f"Staking is not supported on {app.network_label(chain)}. "
            "It is available on Monad and BNB Smart Chain networks."
        )
    return backend.dispatch(app, state, chain, tokens[1], tokens[2:])
