"""Per-chain staking delegation built on Foundry Cast contract calls.

Staking is chain-specific: each supported network has a fixed system contract or
precompile with its own ABI and units. This module keeps one small backend per
chain behind a single ``stake ...`` command surface. All ABI encoding, estimation,
signing, and broadcasting is delegated to Cast; private keys never leave Foundry's
hidden keystore prompt.
"""

from __future__ import annotations

import re
import sys
import time
from string import Template
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
# Multicall3 is deployed at the same address on most EVM chains, including BSC.
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"
_AGGREGATE3 = "aggregate3((address,bool,bytes)[])((bool,bytes)[])"
_BALANCE_OF = "balanceOf(address)(uint256)"

MONAD_DUST_THRESHOLD_WEI = 1_000_000_000  # 1 gwei, per Monad staking API
MONAD_COMMISSION_BASE = 10**18
BSC_COMMISSION_BASE = 10_000
BSC_DEFAULT_LIMIT = 10
BSC_MAX_LIMIT = 45
MONAD_DEFAULT_LIMIT = 10
# Monad validator flags: ok, stake too low, auth address withdrew below the
# minimum, and slashed for double signing (see the staking precompile).
MONAD_VALIDATOR_FLAGS = (
    (1 << 0, "low-stake"),
    (1 << 1, "withdrawn"),
    (1 << 2, "double-sign"),
)
MONAD_KNOWN_FLAGS = sum(bit for bit, _ in MONAD_VALIDATOR_FLAGS)

# The stake target is a validator ID on Monad and an operator address on BNB Smart
# Chain, so usage lines and help name it per chain through $target.
STAKING_USAGE = Template(
    "Usage: stake status [$target] | stake validators [--limit N] [--all] [--full] | "
    "stake info $target [--delegators] | "
    "stake delegate $target AMOUNT [--dry-run | --yes] | stake undelegate $target "
    "(AMOUNT | --all) [--dry-run | --yes] | stake claim $target [--dry-run | --yes]. "
    "Monad also accepts "
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


def _as_address(value: Any, label: str) -> str:
    """Validate and checksum-normalize one address returned by Cast."""
    return validate_address(str(value), label)


def _percent(rate: int, base: int) -> str:
    """Render an integer rate scaled by ``base`` as a percentage with two decimals."""
    hundredths = rate * 10_000 // base
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _monad_status(flags: int) -> str:
    """Render Monad validator flags as a short label such as ``low-stake``."""
    labels = [name for bit, name in MONAD_VALIDATOR_FLAGS if flags & bit]
    if flags & ~MONAD_KNOWN_FLAGS:
        labels.append(f"unknown:{flags & ~MONAD_KNOWN_FLAGS:#x}")
    return "+".join(labels) if labels else "ok"


def _read(app: Application, chain: Chain, address: str, signature: str, *arguments: str) -> Any:
    """Call a read-only contract function and return the decoded JSON value."""
    output = app.cast.network(chain, ["call", address, signature, *arguments], json_output=True)
    return app._parse_json_result(output, "staking")


def _encode_call(app: Application, signature: str, *arguments: str) -> str:
    """ABI-encode calldata for one call; Cast does the encoding, not the CLI."""
    return app.cast.run(["calldata", signature, *arguments])


def _has_code(app: Application, chain: Chain, address: str) -> bool:
    """Return whether an address has runtime code on the selected chain."""
    output = app.cast.network(chain, ["code", address]).strip()
    return output not in {"", "0x", "0x0"}


def _decode_uint(data: str, label: str) -> int:
    """Decode a single ABI-encoded 32-byte unsigned integer."""
    text = data.strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", text):
        raise FoundryError(f"Foundry returned an invalid {label} value.")
    return int(text, 16)


def _multicall(
    app: Application, chain: Chain, calls: list[tuple[str, str]]
) -> list[tuple[bool, str]]:
    """Batch read-only calls with Multicall3 and return ``(success, data)`` pairs."""
    inner = ",".join(f"({target},false,{data})" for target, data in calls)
    output = app.cast.network(
        chain, ["call", MULTICALL3_ADDRESS, _AGGREGATE3, f"[{inner}]"], json_output=True
    )
    # Cast reports one entry per returned value, so the Result[] below is the only one.
    outputs = _as_list(app._parse_json_result(output, "multicall"), "multicall")
    if len(outputs) != 1:
        raise FoundryError("Foundry returned an invalid multicall value.")
    pairs: list[tuple[bool, str]] = []
    for item in _as_list(outputs[0], "multicall"):
        entry = _as_list(item, "multicall result")
        if len(entry) != 2:
            raise FoundryError("Foundry returned an invalid multicall value.")
        pairs.append((bool(entry[0]), str(entry[1])))
    return pairs


def _batch_balances(app: Application, chain: Chain, credits: list[str], holder: str) -> list[int]:
    """Read ``balanceOf(holder)`` for many credit contracts, batching when possible."""
    if _has_code(app, chain, MULTICALL3_ADDRESS):
        data = _encode_call(app, _BALANCE_OF, holder)
        pairs = _multicall(app, chain, [(credit, data) for credit in credits])
        return [
            _decode_uint(returned, "delegation shares") if success else 0
            for success, returned in pairs
        ]
    # Fallback for local chains without Multicall3: one read per credit contract.
    balances: list[int] = []
    for credit in credits:
        value = _as_list(_read(app, chain, credit, _BALANCE_OF, holder), "delegation shares")
        balances.append(_as_int(value[0], "delegation shares"))
    return balances


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
    # User-facing name of the stake target, filled into usage lines and help.
    target_label = "VALIDATOR"
    address = ""

    def usage(self) -> str:
        """Return this chain's stake usage line, naming its own stake target."""
        return STAKING_USAGE.substitute(target=self.target_label)

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
            raise WalletCliError(self.usage())
        return handler(app, state, chain, tokens)

    def status_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    def validators_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    def info_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    def delegate_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    def undelegate_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    def claim_command(
        self, app: Application, state: dict[str, Any], chain: Chain, tokens: list[str]
    ) -> dict[str, Any]:
        raise WalletCliError(self.usage())

    @staticmethod
    def _amount_arguments(tokens: list[str]) -> tuple[bool, bool, list[str]]:
        dry_run = "--dry-run" in tokens
        yes = "--yes" in tokens
        if dry_run and yes:
            raise WalletCliError("Choose either --dry-run or --yes, not both.")
        return dry_run, yes, [t for t in tokens if t not in {"--dry-run", "--yes"}]

    def delegations_summary(
        self, app: Application, chain: Chain, address: str
    ) -> list[dict[str, Any]]:
        """Return the address's delegations for the top-level ``status`` command."""
        return []


class MonadStaking(_StakingBackend):
    """Monad staking precompile (0x1000): validator IDs and MON amounts."""

    chain_names = ("monad", "monad-testnet")
    target_label = "VALIDATOR_ID"
    address = MONAD_STAKING_ADDRESS

    _EPOCH = "getEpoch()(uint64,bool)"
    _VALSET = "getExecutionValidatorSet(uint32)(bool,uint32,uint64[])"
    _CONSENSUS = "getConsensusValidatorSet(uint32)(bool,uint32,uint64[])"
    _VALIDATOR = (
        "getValidator(uint64)(address,uint64,uint256,uint256,uint256,uint256,"
        "uint256,uint256,uint256,uint256,bytes,bytes)"
    )
    _DELEGATOR = (
        "getDelegator(uint64,address)(uint256,uint256,uint256,uint256,uint256,uint64,uint64)"
    )
    _DELEGATIONS = "getDelegations(address,uint64)(bool,uint64,uint64[])"
    _DELEGATORS = "getDelegators(uint64,address)(bool,address,address[])"

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
        flags = _as_int(data[1], "flags")
        return {
            "validator_id": validator_id,
            "auth_address": str(data[0]),
            "flags": flags,
            "status": _monad_status(flags),
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
        validator_ids = self._paginated_ids(app, chain, self._DELEGATIONS, "delegations", address)
        return [
            self._delegator(app, chain, validator_id, address) for validator_id in validator_ids
        ]

    def _paginated_ids(
        self, app: Application, chain: Chain, signature: str, label: str, *prefix: str
    ) -> list[int]:
        """Read every id from a paginated validator-set call, 100 at a time."""
        ids: list[int] = []
        start = 0
        while True:
            data = _as_list(_read(app, chain, self.address, signature, *prefix, str(start)), label)
            done = bool(data[0])
            next_index = _as_int(data[1], "next index")
            batch = [_as_int(item, "validator id") for item in _as_list(data[2], "validator ids")]
            ids.extend(batch)
            if done or not batch or next_index <= start:
                break
            start = next_index
        return ids

    def _delegator_count(self, app: Application, chain: Chain, validator_id: int) -> int:
        """Count a validator's delegators by paging through getDelegators."""
        total = 0
        start = "0x" + "00" * 20
        while True:
            data = _as_list(
                _read(app, chain, self.address, self._DELEGATORS, str(validator_id), start),
                "delegators",
            )
            done = bool(data[0])
            next_delegator = _as_address(data[1], "next delegator")
            total += len(_as_list(data[2], "delegators"))
            if done or next_delegator.lower() == start.lower():
                break
            start = next_delegator
        return total

    def _delegator(
        self, app: Application, chain: Chain, validator_id: int, address: str
    ) -> dict[str, Any]:
        data = _as_list(
            _read(app, chain, self.address, self._DELEGATOR, str(validator_id), address),
            "delegator",
        )
        stake = _as_int(data[0], "stake")
        rewards = _as_int(data[2], "unclaimed rewards")
        pending = _as_int(data[3], "pending stake")
        next_pending = _as_int(data[4], "next pending stake")
        return {
            "validator_id": validator_id,
            "stake_wei": stake,
            "stake": format_units(stake, 18),
            "unclaimed_rewards_wei": rewards,
            "unclaimed_rewards": format_units(rewards, 18),
            "pending_stake_wei": pending,
            "pending_stake": format_units(pending, 18),
            "next_pending_stake_wei": next_pending,
            "next_pending_stake": format_units(next_pending, 18),
            "pending_epoch": _as_int(data[5], "pending epoch"),
            "next_pending_epoch": _as_int(data[6], "next pending epoch"),
        }

    def status_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) > 1:
            raise WalletCliError(f"Usage: stake status [{self.target_label}].")
        epoch, in_delay = self._epoch(app, chain)
        _, metadata, _ = app.wallet(state=state)
        address = metadata["address"]
        if tokens:
            delegations = [self._delegator(app, chain, self._validator_id(tokens[0]), address)]
        else:
            delegations = self.delegations_summary(app, chain, address)
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

    def delegations_summary(self, app, chain, address) -> list[dict[str, Any]]:
        return self._delegations(app, chain, address)

    def validators_command(self, app, state, chain, tokens) -> dict[str, Any]:
        limit, remaining = _limit_option(tokens, default=MONAD_DEFAULT_LIMIT, maximum=500)
        include_all = "--all" in remaining
        include_full = "--full" in remaining
        remaining = [token for token in remaining if token not in {"--all", "--full"}]
        if remaining:
            raise WalletCliError(self.usage())
        epoch, in_delay = self._epoch(app, chain)
        active_ids = self._paginated_ids(app, chain, self._CONSENSUS, "consensus validator set")
        active_set = set(active_ids)
        eligible_ids = active_ids
        if include_all:
            eligible_ids = self._paginated_ids(app, chain, self._VALSET, "validator set")
        # The consensus set arrives ordered by stake, so its first `limit` ids are the top
        # active validators. Only the eligible ids outside it need a read to be ranked
        # alongside them, which keeps the default listing cheap.
        window = active_ids[:limit] + [
            validator_id for validator_id in eligible_ids if validator_id not in active_set
        ]
        validators = [self._validator(app, chain, validator_id) for validator_id in window]
        for item in validators:
            item["active"] = item["validator_id"] in active_set
            if not item["active"] and item["flags"] == 0:
                item["status"] = "inactive"
        validators.sort(key=lambda item: -item["stake_wei"])
        return {
            "command": "stake validators",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "epoch": epoch,
            "in_epoch_delay": in_delay,
            "active_only": not include_all,
            "active_count": len(active_ids),
            "eligible_count": len(eligible_ids),
            "full": include_full,
            "sorted_by": "stake",
            "limit": limit,
            "validators": validators[:limit],
        }

    def info_command(self, app, state, chain, tokens) -> dict[str, Any]:
        include_delegators = "--delegators" in tokens
        args = [token for token in tokens if token != "--delegators"]
        if len(args) != 1:
            raise WalletCliError(f"Usage: stake info {self.target_label} [--delegators].")
        validator_id = self._validator_id(args[0])
        info = self._validator(app, chain, validator_id)
        active_ids = self._paginated_ids(app, chain, self._CONSENSUS, "consensus validator set")
        info["active"] = validator_id in set(active_ids)
        if not info["active"] and info["flags"] == 0:
            info["status"] = "inactive"
        result = {
            "command": "stake info",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            **info,
        }
        if include_delegators:
            result["delegators"] = self._delegator_count(app, chain, validator_id)
        return result

    def delegate_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 2:
            raise WalletCliError(
                f"Usage: stake delegate {self.target_label} AMOUNT [--dry-run | --yes]."
            )
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
        undelegate_all = "--all" in args
        args = [token for token in args if token != "--all"]
        if len(args) != (1 if undelegate_all else 2):
            raise WalletCliError(
                f"Usage: stake undelegate {self.target_label} AMOUNT [--withdraw-id N] "
                f"[--dry-run | --yes] | stake undelegate {self.target_label} --all "
                "[--withdraw-id N] [--dry-run | --yes]."
            )
        validator_id = self._validator_id(args[0])
        if undelegate_all:
            raw = 0  # resolved from the delegator's active stake below
        else:
            raw = to_base_units(args[1], 18)
        withdraw_id = 0
        if withdraw_raw is not None:
            try:
                withdraw_id = int(withdraw_raw, 10)
            except ValueError:
                raise WalletCliError("--withdraw-id must be between 0 and 255.") from None
        if not 0 <= withdraw_id <= 255:
            raise WalletCliError("--withdraw-id must be between 0 and 255.")
        # The delegator read costs a call and needs a wallet, so it comes after
        # the arguments have been checked.
        _, metadata, _ = app.wallet(state=state)
        delegator = self._delegator(app, chain, validator_id, metadata["address"])
        if undelegate_all:
            raw = delegator["stake_wei"]
            if raw == 0:
                raise WalletCliError(
                    f"No active stake to undelegate from validator {validator_id}; "
                    "pending delegations cannot be undelegated until they activate."
                )
        amount = format_units(raw, 18)
        preview = {
            "validator_id": str(validator_id),
            "amount": f"{amount} MON",
            "withdraw_id": str(withdraw_id),
        }
        if undelegate_all:
            preview["scope"] = "all active stake"
        # Pending delegations cannot be undelegated, and rewards are paid by
        # claimRewards rather than by undelegate, so neither is part of the amount
        # above. Say so before the user signs instead of after.
        pending = delegator["pending_stake_wei"] + delegator["next_pending_stake_wei"]
        if pending:
            preview["pending_stake"] = (
                f"{format_units(pending, 18)} MON not undelegatable until it activates"
            )
        if delegator["unclaimed_rewards_wei"]:
            preview["unclaimed_rewards"] = (
                f"{delegator['unclaimed_rewards']} MON not claimed; "
                f"run `stake claim {validator_id}`"
            )
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
            preview=preview,
            record={
                "validator_id": validator_id,
                "amount": amount,
                "amount_base_units": str(raw),
                "withdraw_id": withdraw_id,
                "all": undelegate_all,
            },
            dry_run=dry_run,
            yes=yes,
        )

    def claim_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) != 1:
            raise WalletCliError(f"Usage: stake claim {self.target_label} [--dry-run | --yes].")
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
                f"Usage: stake withdraw {self.target_label} WITHDRAW_ID [--dry-run | --yes]."
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
            raise WalletCliError(f"Usage: stake compound {self.target_label} [--dry-run | --yes].")
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
    target_label = "OPERATOR"
    address = BSC_STAKE_HUB_ADDRESS

    _UNBOND = "unbondPeriod()(uint256)"
    _MIN_SELF = "minSelfDelegationBNB()(uint256)"
    _MIN_CHANGE = "minDelegationBNBChange()(uint256)"
    _MAX_ELECTED = "maxElectedValidators()(uint256)"
    _VALIDATORS = "getValidators(uint256,uint256)(address[],address[],uint256)"
    _ELECTION = "getValidatorElectionInfo(uint256,uint256)(address[],uint256[],bytes[],uint256)"
    _POOLED = "getPooledBNB(address)(uint256)"
    _PENDING_UNBOND = "pendingUnbondRequest(address)(uint256)"
    _CLAIMABLE_UNBOND = "claimableUnbondRequest(address)(uint256)"
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

    def _validator_credits(self, app: Application, chain: Chain) -> list[tuple[str, str]]:
        """Return every ``(operator, credit contract)`` pair in the validator set."""
        data = _as_list(_read(app, chain, self.address, self._VALIDATORS, "0", "0"), "validators")
        operators = [
            _as_address(item, "operator address") for item in _as_list(data[0], "operators")
        ]
        credits = [_as_address(item, "credit contract") for item in _as_list(data[1], "credits")]
        return list(zip(operators, credits))

    def _delegation(
        self,
        app: Application,
        chain: Chain,
        operator: str,
        address: str,
        *,
        credit: str | None = None,
        shares: int | None = None,
    ) -> dict[str, Any]:
        """Describe one delegator/validator position from the StakeCredit contract."""
        if credit is None:
            credit = self._credit_contract(app, chain, operator)
        if shares is None:
            shares = _as_int(
                _as_list(_read(app, chain, credit, _BALANCE_OF, address), "shares")[0],
                "shares",
            )
        pooled = _as_int(
            _as_list(_read(app, chain, credit, self._POOLED, address), "balance")[0], "balance"
        )
        rate = self._commission_rate(app, chain, operator)
        return {
            "operator": operator,
            "credit_contract": credit,
            "shares": str(shares),
            "pooled_bnb_wei": pooled,
            "pooled_bnb": format_units(pooled, 18),
            "commission": _percent(rate, BSC_COMMISSION_BASE),
            "pending_unbond_requests": _as_int(
                _as_list(_read(app, chain, credit, self._PENDING_UNBOND, address), "pending")[0],
                "pending unbond requests",
            ),
            "claimable_unbond_requests": _as_int(
                _as_list(_read(app, chain, credit, self._CLAIMABLE_UNBOND, address), "claimable")[
                    0
                ],
                "claimable unbond requests",
            ),
        }

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
            raise WalletCliError(f"Usage: stake status [{self.target_label}].")
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
        return {
            "command": "stake status",
            "chain": app.network_label(chain),
            "chain_id": chain.chain_id,
            "address": address,
            "parameters": parameters,
            "delegation": self._delegation(app, chain, operator, address),
        }

    def delegations_summary(self, app, chain, address) -> list[dict[str, Any]]:
        """Find the address's delegations across the validator set's credit contracts."""
        pairs = self._validator_credits(app, chain)
        balances = _batch_balances(app, chain, [credit for _, credit in pairs], address)
        return [
            self._delegation(app, chain, operator, address, credit=credit, shares=shares)
            for (operator, credit), shares in zip(pairs, balances)
            if shares > 0
        ]

    def _delegation(
        self,
        app: Application,
        chain: Chain,
        operator: str,
        address: str,
        *,
        credit: str | None = None,
        shares: int | None = None,
    ) -> dict[str, Any]:
        """Describe one delegator/validator position from the StakeCredit contract."""
        if credit is None:
            credit = self._credit_contract(app, chain, operator)
        if shares is None:
            shares = _as_int(
                _as_list(_read(app, chain, credit, _BALANCE_OF, address), "shares")[0],
                "shares",
            )
        pooled = _as_int(
            _as_list(_read(app, chain, credit, self._POOLED, address), "balance")[0], "balance"
        )
        rate = self._commission_rate(app, chain, operator)
        return {
            "operator": operator,
            "credit_contract": credit,
            "shares": str(shares),
            "pooled_bnb_wei": pooled,
            "pooled_bnb": format_units(pooled, 18),
            "commission": _percent(rate, BSC_COMMISSION_BASE),
            "pending_unbond_requests": _as_int(
                _as_list(_read(app, chain, credit, self._PENDING_UNBOND, address), "pending")[0],
                "pending unbond requests",
            ),
            "claimable_unbond_requests": _as_int(
                _as_list(_read(app, chain, credit, self._CLAIMABLE_UNBOND, address), "claimable")[
                    0
                ],
                "claimable unbond requests",
            ),
        }

    def validators_command(self, app, state, chain, tokens) -> dict[str, Any]:
        limit, remaining = _limit_option(tokens, default=BSC_DEFAULT_LIMIT, maximum=BSC_MAX_LIMIT)
        if remaining:
            raise WalletCliError(self.usage())
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
            "sorted_by": "stake",
            "limit": limit,
            "validators": sorted(validators, key=lambda item: -item["stake_wei"]),
        }

    def info_command(self, app, state, chain, tokens) -> dict[str, Any]:
        if len(tokens) != 1:
            raise WalletCliError(f"Usage: stake info {self.target_label}.")
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
                f"Usage: stake delegate {self.target_label} AMOUNT [--no-vote-power] "
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
        undelegate_all = "--all" in args
        args = [token for token in args if token not in {"--shares", "--all"}]
        if shares_only and undelegate_all:
            raise WalletCliError("Choose either --shares or --all, not both.")
        if len(args) != (1 if undelegate_all else 2):
            raise WalletCliError(
                f"Usage: stake undelegate {self.target_label} AMOUNT [--shares] "
                f"[--dry-run | --yes] | stake undelegate {self.target_label} --all "
                "[--dry-run | --yes]."
            )
        operator = validate_address(args[0], "operator address")
        preview_scope: str | None = None
        if undelegate_all:
            # Stake is held as shares in the validator's credit contract, so the
            # delegator's whole position is that balance.
            _, metadata, _ = app.wallet(state=state)
            credit = self._credit_contract(app, chain, operator)
            shares = _as_int(
                _as_list(
                    _read(app, chain, credit, _BALANCE_OF, metadata["address"]),
                    "shares",
                )[0],
                "shares",
            )
            if shares <= 0:
                raise WalletCliError(f"No stake to undelegate from {operator}.")
            amount = format_units(shares, 18)
            preview_amount = f"{amount} BNB-equivalent"
            preview_scope = "all delegated shares"
        elif shares_only:
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
        preview = {"operator": operator, "amount": preview_amount, "shares": str(shares)}
        if preview_scope:
            preview["scope"] = preview_scope
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
            preview=preview,
            record={
                "operator": operator,
                "amount": amount,
                "shares": str(shares),
                "all": undelegate_all,
            },
            dry_run=dry_run,
            yes=yes,
        )

    def claim_command(self, app, state, chain, tokens) -> dict[str, Any]:
        dry_run, yes, args = self._amount_arguments(tokens)
        if len(args) not in {1, 2}:
            raise WalletCliError(
                f"Usage: stake claim {self.target_label} [REQUEST_NUMBER] [--dry-run | --yes]."
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


def status_delegations(app: Application, chain: Chain, address: str) -> list[dict[str, Any]] | None:
    """Return an address's staking delegations, or ``None`` when staking is unsupported."""
    backend = _BACKENDS.get(chain.name)
    if backend is None:
        return None
    return backend.delegations_summary(app, chain, address)


def target_label_for(chain_name: str) -> str:
    """Return the user-facing name of a chain's stake target, for help text."""
    backend = _BACKENDS.get(chain_name)
    return backend.target_label if backend else _StakingBackend.target_label


def handle_stake(app: Application, tokens: list[str]) -> dict[str, Any]:
    """Dispatch a ``stake ...`` command to the backend for the active chain."""
    state = app.config()
    chain = app.active_chain(state)
    backend = _BACKENDS.get(chain.name)
    if backend is None:
        raise WalletCliError(
            f"Staking is not supported on {app.network_label(chain)}. "
            "It is available on Monad and BNB Smart Chain networks."
        )
    if len(tokens) < 2:
        raise WalletCliError(backend.usage())
    return backend.dispatch(app, state, chain, tokens[1], tokens[2:])
