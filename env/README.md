# Optional deployment configuration

Both launchers work without environment files. Ethereum and Monad each have their
own fixed network choices, configuration directory, and environment prefix.

For testnets, export the values in `dev.env.example` for Ethereum Sepolia or
`monad.env.example` for Monad Testnet before running the corresponding launcher.
A private copy can use the `.env` extension (ignored by Git). The CLI does not load
these files automatically. The launchers default to the public
`ghcr.io/vibe-wallets/ethereum-wallet-cli:main` image and pull it before each run;
set the profile's `*_WALLET_IMAGE=ethereum-wallet-cli:local` only after a local
`make build`. Remote images are pulled each time, and a pull failure stops the
launch. When the package is public, pulls need no login; while it is private, the
launcher uses the caller's existing `ghcr.io` Docker credentials.

The launcher forwards only its own wallet network and RPC settings into the
container. The optional `ETHEREUM_WALLET_DOCKER_NETWORK` or
`MONAD_WALLET_DOCKER_NETWORK` setting chooses the Docker network for local test-node
containers; it is used by Docker and is not passed into the wallet. With no value,
Docker's default network applies. Do not store private keys or keystore passwords
in environment files.
