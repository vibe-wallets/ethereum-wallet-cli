# Optional deployment configuration

Both launchers work without environment files. Ethereum and Monad each have their
own fixed network choices, configuration directory, and environment prefix.

For testnets, export the values in `dev.env.example` for Ethereum Sepolia or
`monad.env.example` for Monad Testnet before running the corresponding launcher.
A private copy can use the `.env` extension (ignored by Git). The CLI does not load
these files automatically. The launcher forwards only its own network and RPC settings.
Do not store private keys or keystore passwords in environment files.
