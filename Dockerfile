# Foundry owns encryption, ABI encoding, RPC and signing. Pin tested tools.
FROM ghcr.io/foundry-rs/foundry:v1.8.5@sha256:32c8ea9ef052a440cb1620175987a3f49eff8b068a0c6a3d09ebf7f5f9a0e043 AS foundry

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

LABEL org.opencontainers.image.source="https://github.com/vibe-wallets/ethereum-wallet-cli"
LABEL org.opencontainers.image.description="Foundry-backed Ethereum and Monad wallet CLIs"

WORKDIR /app

# Ship only the pinned Foundry binaries the wallet shells out to.
COPY --from=foundry /usr/local/bin/cast /usr/local/bin/cast
COPY --from=foundry /usr/local/bin/anvil /usr/local/bin/anvil

# Run as an unprivileged user; the mounted /data is the only persistent path.
RUN groupadd --gid 10001 wallet \
    && useradd --uid 10001 --gid wallet --no-create-home --home-dir /data wallet \
    && mkdir /data \
    && chown wallet:wallet /data \
    && chmod 700 /data

COPY src /app/src
COPY scripts/container/ /usr/local/bin/

# Both entry points share one image and receive their own /data mount.
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    ETHEREUM_WALLET_CONFIG_DIR=/data \
    MONAD_WALLET_CONFIG_DIR=/data

USER 10001:10001
ENTRYPOINT ["ethereum-wallet-cli"]
