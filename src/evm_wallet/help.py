"""Human-readable command index and focused help topics.

``help`` with no topic prints the index; ``help TOPIC`` prints one focused page.
Section headings are uppercase so :func:`evm_wallet.human.style_help` can style
them on a terminal without changing the plain text.
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
  help [TOPIC]                     Show this index or one focused topic
  clear                            Clear the screen
  exit | quit                      Leave the shell

Amounts are exact decimal strings. Sends require an interactive terminal to unlock
the encrypted keystore; --yes skips the transaction confirmation prompt.
Run `help TOPIC` for focused help: wallet, chain, status, send, token, tx,
address, balance, nonce, gas, history.
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

DESTINATION is a 0x-prefixed 20-byte address and AMOUNT is an exact decimal
string such as 0.01. The command estimates gas first:
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
""",
    "nonce": """NONCE

nonce [ADDRESS]
  Show the next transaction nonce for ADDRESS, counting pending transactions, or
  for the selected wallet by default.
""",
    "gas": """GAS

gas
  Show the current gas price reported by the selected network's RPC endpoint, in
  wei and gwei. It is an estimate, not a fee guarantee.
""",
    "history": """HISTORY

history [COUNT]
  Show the most recent shell commands (default 20). History is stored as plain
  command text in the profile's config directory; secret values are never part of
  a command.
""",
}


def help_text(topic: str | None = None) -> str:
    """Return the command index or one focused help topic."""
    if topic is None:
        return HELP_INDEX
    normalized = topic.strip().lower()
    return HELP_TOPICS.get(
        normalized,
        f"No detailed help is available for `{topic}`. Run `help` for the command list.",
    )


def topic_names() -> list[str]:
    """Return the sorted focused help topics, for completion and validation."""
    return sorted(HELP_TOPICS)
