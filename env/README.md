# Optional deployment configuration

All launchers work without environment files. Ethereum, Monad, and BNB Smart Chain
each have their own fixed network choices, configuration directory, and environment
prefix.

For testnets, export the values in `dev.env.example` for Ethereum Sepolia,
`monad.env.example` for Monad Testnet, or `bsc.env.example` for BSC Testnet before
running the corresponding launcher.
A private copy can use the `.env` extension (ignored by Git). The CLI does not load
these files automatically. The launchers default to the public
`ghcr.io/vibe-wallets/ethereum-wallet-cli:main` image and pull it before each run;
set the profile's `*_WALLET_IMAGE=ethereum-wallet-cli:local` only after a local
`make build`. Remote images are pulled each time, and a pull failure stops the
launch. When the package is public, pulls need no login; while it is private, the
launcher uses the caller's existing `ghcr.io` Docker credentials.

The launcher forwards only its own wallet network and RPC settings into the
container. The profile's `*_WALLET_RPC_URL` overrides the built-in public endpoint
for the selected network, which is how you point a profile at a different node
provider today (the built-in defaults use PublicNode). The optional
`ETHEREUM_WALLET_DOCKER_NETWORK`, `MONAD_WALLET_DOCKER_NETWORK`, or
`BSC_WALLET_DOCKER_NETWORK` setting chooses the Docker network for local test-node
containers; it is used by Docker and is not passed into the wallet. With no value,
Docker's default network applies. Do not store private keys or keystore passwords
in environment files.
