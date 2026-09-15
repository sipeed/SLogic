#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-lock", required=True, type=Path)
    parser.add_argument("--workspace-commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", required=True, choices=("nightly", "release"))
    parser.add_argument("--build-type", required=True, choices=("Debug", "Release"))
    parser.add_argument("--target", required=True)
    parser.add_argument("--products", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    lock = json.loads(args.sources_lock.read_text())
    artifacts = sorted(
        path for path in args.output.iterdir()
        if path.is_file() and path.name not in {"build-info.json", "SHA256SUMS"}
    )
    info = {
        "version": args.version,
        "channel": args.channel,
        "build_type": args.build_type,
        "target": args.target,
        "products": [item for item in args.products.split(",") if item],
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "builder": {"system": platform.system(), "machine": platform.machine()},
        "workspace": {
            "commit": args.workspace_commit,
            "dirty": lock.get("workspace_dirty", False),
            "sources": lock["sources"],
        },
        "artifacts": [{"name": path.name, "sha256": sha256(path)} for path in artifacts],
    }
    with (args.output / "build-info.json").open("w", encoding="utf-8") as stream:
        json.dump(info, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with (args.output / "SHA256SUMS").open("w", encoding="utf-8") as stream:
        for artifact in info["artifacts"]:
            stream.write(f"{artifact['sha256']}  {artifact['name']}\n")


if __name__ == "__main__":
    main()
