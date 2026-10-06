"""Write CI-only GHCR credentials into an explicit runner-temporary directory.

This never reads or changes the caller's existing Docker configuration, and never
prints credentials. GitHub Actions supplies its own repository-scoped job token.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    args = parser.parse_args()
    username = os.environ.get("REGISTRY_USER")
    token = os.environ.get("REGISTRY_TOKEN")
    if not username or not token:
        parser.error("REGISTRY_USER and REGISTRY_TOKEN must be set by the CI job")
    directory = args.config_dir
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        parser.error("CI Docker config directory must be a real directory")
    os.chmod(directory, 0o700)
    path = directory / "config.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"auths": {"ghcr.io": {"auth": encoded}}}, handle)
        handle.write("\n")


if __name__ == "__main__":
    main()
