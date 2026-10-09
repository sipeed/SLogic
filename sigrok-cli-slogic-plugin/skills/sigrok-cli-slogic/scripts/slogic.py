#!/usr/bin/env python3
"""Thin cross-platform forwarder to a user-provided sigrok-cli binary.

The wrapper only locates the sigrok-cli executable across Linux/macOS/Windows,
adds its bundled libraries to the dynamic-linker path, and forwards every other
argument to it unchanged. It intentionally encodes no sigrok-cli options:
discover them from the binary itself with `-- --help`, `-- -L`, or
`-- --driver <driver> --show`.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


USAGE = (
    "usage: slogic.py [--sigrok-cli PATH] [--] SIGROK_CLI_ARGS...\n"
    "\n"
    "Thin forwarder to a SLogic-capable sigrok-cli. The binary is chosen from\n"
    "--sigrok-cli, else $SIGROK_CLI, else the current directory, else PATH; every\n"
    "other argument is passed through unchanged. Ask sigrok-cli itself for options:\n"
    "  slogic.py -- --version\n"
    "  slogic.py -- -L                                      # drivers and decoders\n"
    "  slogic.py -- --driver sipeed-slogic-analyzer --scan\n"
    "  slogic.py -- --driver sipeed-slogic-analyzer --show  # rates, channels, ...\n"
    "  slogic.py -- --help\n"
)


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def cli_names(platform: str) -> tuple[str, ...]:
    return ("sigrok-cli.exe", "sigrok-cli") if platform == "windows" else ("sigrok-cli",)


def expand_cli_candidate(candidate: Path, platform: str) -> list[Path]:
    candidate = candidate.expanduser()
    if platform == "macos" and candidate.suffix.lower() == ".dmg":
        raise SystemExit(
            "a .dmg is a disk image, not a sigrok-cli executable; mount it and pass either the "
            ".app bundle or its Contents/MacOS/sigrok-cli executable"
        )
    if candidate.is_dir():
        paths: list[Path] = []
        if platform == "macos" and candidate.suffix.lower() == ".app":
            paths.append(candidate / "Contents/MacOS/sigrok-cli")
        for name in cli_names(platform):
            paths.extend((candidate / name, candidate / "bin" / name, candidate / "sr/bin" / name))
        return paths
    return [candidate]


def usable_cli(candidate: Path, platform: str) -> bool:
    if not candidate.is_file():
        return False
    if platform == "windows":
        return candidate.suffix.lower() in {".exe", ".com", ".bat", ".cmd"}
    return os.access(candidate, os.X_OK)


def resolve_cli(explicit: str | None, *, platform: str | None = None) -> Path:
    platform = platform or platform_name()
    candidates: list[Path] = []
    if explicit:
        candidates.extend(expand_cli_candidate(Path(explicit), platform))
    elif os.environ.get("SIGROK_CLI"):
        candidates.extend(expand_cli_candidate(Path(os.environ["SIGROK_CLI"]), platform))
    else:
        for name in cli_names(platform):
            candidates.extend((Path.cwd() / name, Path.cwd() / "bin" / name, Path.cwd() / "sr/bin" / name))
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for candidate in candidates:
        candidate = candidate.resolve()
        if usable_cli(candidate, platform):
            return candidate
    rendered = ", ".join(str(p) for p in candidates) or "(none)"
    raise SystemExit(f"sigrok-cli not found or not executable; checked: {rendered}")


def prepend_env_path(env: dict[str, str], key: str, paths: list[Path]) -> None:
    existing = env.get(key)
    values = [str(path) for path in paths if path.is_dir()]
    if existing:
        values.append(existing)
    if values:
        env[key] = os.pathsep.join(values)


def command_env(cli: Path, *, platform: str | None = None) -> dict[str, str]:
    platform = platform or platform_name()
    env = os.environ.copy()
    adjacent = [cli.parent, cli.parent / "lib", cli.parent.parent / "lib"]
    if platform == "windows":
        prepend_env_path(env, "PATH", adjacent)
    elif platform == "macos":
        frameworks = cli.parent.parent / "Frameworks"
        prepend_env_path(env, "DYLD_LIBRARY_PATH", [frameworks, *adjacent[1:]])
    else:
        prepend_env_path(env, "LD_LIBRARY_PATH", adjacent[1:])
    return env


def execute(cli: Path, args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [str(cli), *args]
    rendered = subprocess.list2cmdline(cmd) if platform_name() == "windows" else " ".join(
        repr(part) if any(char.isspace() for char in part) else part for part in cmd
    )
    print("+ " + rendered, file=sys.stderr)
    return subprocess.run(
        cmd,
        env=command_env(cli),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=False,
    )


def split_args(argv: list[str]) -> tuple[str | None, list[str]]:
    """Split wrapper argv into (explicit sigrok-cli path or None, args to forward).

    `--sigrok-cli PATH` (or `--sigrok-cli=PATH`) is only recognized as the first
    token, so it never shadows a sigrok-cli option of the same spelling; an
    optional leading `--` separates the binary selector from forwarded args.
    """
    explicit: str | None = None
    rest = list(argv)
    if rest and rest[0] == "--sigrok-cli":
        if len(rest) < 2:
            raise SystemExit("--sigrok-cli requires a path")
        explicit, rest = rest[1], rest[2:]
    elif rest and rest[0].startswith("--sigrok-cli="):
        explicit, rest = rest[0].split("=", 1)[1], rest[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    return explicit, rest


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(USAGE)
        return 2
    explicit, forward = split_args(argv)
    if not forward:
        sys.stderr.write("no sigrok-cli arguments to forward\n\n" + USAGE)
        return 2
    cli = resolve_cli(explicit)
    return execute(cli, forward).returncode


if __name__ == "__main__":
    raise SystemExit(main())
