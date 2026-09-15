"""Minimal TOML reader for SLogic's build declarations.

This keeps the build entry points usable with Apple's Python versions that
predate the standard-library tomllib module.  SLogic declarations deliberately
use only scalar values, arrays of scalar values, and one level of [table]
sections.
"""

from __future__ import annotations

import ast


def loads(content: str) -> dict:
    result: dict = {}
    scope = result
    for line_number, source_line in enumerate(content.splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            if not name or "." in name or "[" in name:
                raise ValueError(f"unsupported TOML table on line {line_number}")
            scope = result.setdefault(name, {})
            continue
        if "=" not in line:
            raise ValueError(f"unsupported TOML syntax on line {line_number}")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key or "." in key:
            raise ValueError(f"unsupported TOML key on line {line_number}")
        if raw_value == "true":
            value = True
        elif raw_value == "false":
            value = False
        else:
            try:
                value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError) as error:
                raise ValueError(
                    f"unsupported TOML value on line {line_number}"
                ) from error
        scope[key] = value
    return result
