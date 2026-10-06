"""Human-readable command index and focused help topics.

``help`` prints the common command index; ``help --verbose`` (or a session started
with ``--verbose``) additionally lists the advanced commands. ``help TOPIC``
prints one focused page. Section headings are uppercase so
:func:`evm_wallet.human.style_help` can style them on a terminal without changing
the plain text.
"""

from __future__ import annotations

HELP_INDEX = """COMMANDS

WALLETS
  wallet new ALIAS                 Create an encrypted Foundry keystore
  wallet import ALIAS              Import a private key through hidden prompts
  wallet list                      List wallets and mark current/default
  wallet use ALIAS                 Select a wallet for this shell session
  wallet default ALIAS             Choose the default wallet for later runs
  wallet info [ALIAS]              Show a wallet's public address and keystore
  wallet rename OLD NEW            Rename a local wallet alias
  wallet delete ALIAS [--yes]      Delete a local keystore (asks first)

READS
  address [ALIAS]                  Show a wallet address
  balance [ADDRESS]                Show a native coin balance
  nonce [ADDRESS]                  Show the next transaction nonce
  gas                              Show the current gas price
  token balance CONTRACT [ADDRESS] Show an ERC-20 balance

NETWORKS
  chain list                       List mainnet, testnet, and local networks
  chain info [NETWORK]             Show one network's chain ID and RPC URL
  status                           Refresh wallet, network, and native balance

TRANSFERS
  send DESTINATION AMOUNT [--dry-run | --yes]
  token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]

INSPECTION
  tx inspect HASH                  Show a transaction and its receipt
  history [COUNT]                  Show recent shell commands

UTILITIES
  help [TOPIC] [--verbose]         Show this index or one focused topic
  clear                            Clear the screen
  exit | quit                      Leave the shell

Amounts are exact decimal strings. Sends require an interactive terminal to unlock
the encrypted keystore; --yes skips the transaction confirmation prompt.
Run `help TOPIC` for focused help: wallet, chain, status, send, token, tx,
address, balance, nonce, gas, history.
Advanced commands are hidden; run `help --verbose` to show them.
"""

ADVANCED_INDEX = """
ADVANCED
  config show                      Show resolved profile, network, and storage
  call CONTRACT SIGNATURE [ARGS...] Read a view function on a contract
  checksum ADDRESS                 EIP-55 checksum an address
  block [NUMBER|latest]            Show a block header
  contact add NAME ADDRESS         Save a local address-book entry
  contact list | remove NAME       List or remove contacts
  estimate DESTINATION AMOUNT      Gas estimate only, without signing
  token info CONTRACT              Show ERC-20 name, symbol, decimals, supply
  token list [ADDRESS]             Show balances for saved tokens
  token add CONTRACT [SYMBOL]      Save a token for this network
  token remove CONTRACT            Forget a saved token
  token allowance CONTRACT SPENDER [OWNER]
                                   Show an ERC-20 allowance
  token revoke CONTRACT SPENDER [--dry-run | --yes]
                                   Reset an ERC-20 allowance to zero
  tx list [COUNT]                  Show transactions this CLI broadcast
  tx watch HASH                    Wait for a transaction receipt
  wallet watch ALIAS ADDRESS       Track an address without a keystore
  wallet verify [ALIAS]            Re-check local wallet files
"""

HELP_TOPICS: dict[str, str] = {
    "wallet": """WALLET COMMANDS

wallet new ALIAS
  Create a new encrypted keystore with Foundry's hidden passphrase prompt.
wallet import ALIAS
  Import a private key through Foundry's hidden prompts.
wallet list
  List aliases and mark the current session wallet and the saved default.
wallet use ALIAS
  Select a wallet for the current shell session only.
wallet default ALIAS
  Save a default wallet for future runs of this profile.
wallet info [ALIAS]
  Show the public address and encrypted keystore path.
wallet rename OLD NEW
  Rename a local alias; the encrypted keystore is unchanged.
wallet delete ALIAS [--yes]
  Delete the local encrypted keystore. On-chain funds are never touched. The
  command asks for confirmation unless --yes is given.

The Ethereum and Monad launchers keep separate stores, so an alias exists in one
profile only unless you import the same key into both.
""",
    "chain": """NETWORK COMMANDS

chain list
  List the fixed mainnet, testnet, and local networks for this profile.
chain info [NETWORK]
  Show one network's chain ID and RPC URL; defaults to the current network.

Network choice is fixed by the launcher and applies to this run or shell session.
Use --network mainnet|testnet|local at startup, or --rpc-url URL for the current
process. The CLI checks the endpoint's chain ID before any RPC operation.
""",
    "status": """STATUS

status
  Verify the selected network, then show the selected wallet, its address, and
  its native coin balance. If no wallet is selected, it still checks the network
  and reports that no wallet is active.
""",
    "send": """SEND NATIVE COIN

send DESTINATION AMOUNT [--dry-run | --yes]

DESTINATION is a 0x-prefixed 20-byte address or a saved contact name, and AMOUNT
is an exact decimal string such as 0.01. The command estimates gas first:
  --dry-run  print the estimate and do not sign or broadcast
  (default)  ask for confirmation, then sign through Foundry's hidden prompt
  --yes      skip only the confirmation prompt; signing still needs a terminal

A submitted transaction can still be pending, replaced, dropped, or reverted.
Check its receipt with `tx inspect HASH` before retrying.
""",
    "token": """ERC-20 COMMANDS

token balance CONTRACT [ADDRESS]
  Read a token balance. ADDRESS defaults to the selected wallet.
token send CONTRACT DESTINATION AMOUNT [--dry-run | --yes]
  Simulate, estimate, confirm, and send an ERC-20 transfer.

The amount is human-readable token units; decimals are read from the contract.
The command refuses to sign if the transfer simulation returns false.
""",
    "tx": """TRANSACTION INSPECTION

tx inspect HASH
  Show the transaction and, when it is mined, its receipt. A null receipt means
  the transaction is still pending. A submitted hash proves only that a node
  accepted the broadcast request, not that the transaction succeeded.
""",
    "address": """ADDRESS

address [ALIAS]
  Print a wallet's public address without unlocking the keystore. Defaults to the
  selected wallet for this session or the saved default.
""",
    "balance": """BALANCE

balance [ADDRESS]
  Read the native coin balance for ADDRESS, or for the selected wallet by default.
  ADDRESS may also be a saved contact name.
""",
    "nonce": """NONCE

nonce [ADDRESS]
  Show the next transaction nonce for ADDRESS, counting pending transactions, or
  for the selected wallet by default.
""",
    "gas": """GAS

gas
  Show the current gas price and base fee reported by the selected network's RPC
  endpoint, in wei and gwei. They are estimates, not a fee guarantee.
""",
    "history": """HISTORY

history [COUNT]
  Show the most recent shell commands (default 20). History is stored as plain
  command text in the profile's config directory; secret values are never part of
  a command.
""",
}

# Extra help appended to a base topic only when verbose mode is on.
ADVANCED_EXTRA: dict[str, str] = {
    "wallet": """
wallet watch ALIAS ADDRESS
  Track an address without a keystore. A watch-only wallet can be read from but
  never signs.
wallet verify [ALIAS]
  Re-check that each local keystore is readable, consistent, and correctly
  permissioned. Useful before relying on a backup.
""",
    "token": """
token info CONTRACT
  Show the token's name, symbol, decimals, and total supply.
token list [ADDRESS]
  Read balances for the tokens saved on this network. ADDRESS defaults to the
  selected wallet.
token add CONTRACT [SYMBOL]
  Save a token for the current network so `token list` can show it. The symbol is
  read from the contract when omitted.
token remove CONTRACT
  Forget a saved token.
token allowance CONTRACT SPENDER [OWNER]
  Show how many token units SPENDER may move from OWNER's account.
token revoke CONTRACT SPENDER [--dry-run | --yes]
  Reset an allowance to zero. This is a real transaction and always asks before
  signing unless --yes is given.
""",
    "tx": """
tx list [COUNT]
  Show transactions this CLI broadcast on the current network, newest last.
  RPC endpoints cannot enumerate history, so only local sends are recorded.
tx watch HASH
  Poll until the transaction is mined, then show its receipt.
""",
}

# Standalone topics for the advanced commands; ``help TOPIC`` needs verbose mode.
ADVANCED_TOPICS: dict[str, str] = {
    "config": """CONFIG

config show
  Show the resolved profile, network, chain ID, RPC URL, config directory, wallet,
  watch-only status, and saved contact/token counts. It makes no network request.
""",
    "call": """CONTRACT CALL

call CONTRACT SIGNATURE [ARGS...]

Run a read-only view function, for example:

  call 0xTokenContract "balanceOf(address)(uint256)" 0xWalletAddress
  call 0xTokenContract "decimals()(uint8)"

The result is printed as Cast returns it. This never signs or broadcasts.
""",
    "checksum": """CHECKSUM

checksum ADDRESS
  Print the EIP-55 mixed-case checksum form of a lowercase address. This is a
  local operation and makes no network request.
""",
    "block": """BLOCK

block [NUMBER|latest]
  Show a block header: number, hash, timestamp, gas limit, gas used, base fee, and
  transaction count. NUMBER may be decimal or 0x-prefixed; the default is latest.
""",
    "contact": """CONTACTS

contact add NAME ADDRESS
  Save an address-book entry. The address may be another contact's name.
contact list
  List saved contacts.
contact remove NAME
  Remove a contact.

Saved contact names can be used wherever an address is expected, such as
`send NAME 0.1` or `balance NAME`.
""",
    "estimate": """ESTIMATE

estimate DESTINATION AMOUNT
  Estimate gas for a native transfer without signing or broadcasting. It accepts
  a contact name and behaves like `send DESTINATION AMOUNT --dry-run`.
""",
}

_NO_TOPIC = "No detailed help is available for `{topic}`. Run `help` for the command list."
_NEEDS_VERBOSE = (
    "`{topic}` is an advanced command. Run `help --verbose` or start the shell with "
    "`--verbose` to see its help."
)


def help_text(topic: str | None = None, *, verbose: bool = False) -> str:
    """Return the command index or one focused help topic.

    Advanced commands are only listed, and advanced-only topics only explained,
    when ``verbose`` is true.
    """
    if topic is None:
        return HELP_INDEX + (ADVANCED_INDEX if verbose else "")
    normalized = topic.strip().lower()
    if normalized in ADVANCED_TOPICS:
        return ADVANCED_TOPICS[normalized] if verbose else _NEEDS_VERBOSE.format(topic=topic)
    if normalized in HELP_TOPICS:
        text = HELP_TOPICS[normalized]
        if verbose:
            text += ADVANCED_EXTRA.get(normalized, "")
        return text
    return _NO_TOPIC.format(topic=topic)


def topic_names() -> list[str]:
    """Return all help topic names, for completion and validation."""
    return sorted(set(HELP_TOPICS) | set(ADVANCED_TOPICS))
