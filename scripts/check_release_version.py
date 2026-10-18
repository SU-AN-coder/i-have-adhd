#!/usr/bin/env python3
"""Check that a release tag matches the version in every plugin manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

# Manifests that carry a `version`, and therefore have to agree on it. `plugin.json`
# (Antigravity) is deliberately absent: Antigravity documents plugin.json as a marker
# file with an optional name field, so it has never carried a version.
MANIFESTS = (
    "package.json",
    "kimi.plugin.json",
    "gemini-extension.json",
    "qwen-extension.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
)

# The tag the release workflow creates. A pre-release suffix is allowed so
# `v0.4.1-rc1` can ship before `v0.4.1` does; only the version part is matched.
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-[0-9A-Za-z.-]+)?$")


def manifest_versions(root: Path = ROOT) -> dict[str, str]:
    """Return the version each manifest declares, keyed by manifest path."""
    versions: dict[str, str] = {}
    for name in MANIFESTS:
        try:
            payload = json.loads((root / name).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"{name}: manifest not found") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name}: invalid JSON: {exc}") from exc
        version = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{name}: version must be a non-empty string")
        versions[name] = version
    return versions


def declared_version(versions: dict[str, str]) -> str:
    """Return the single version the manifests agree on, or fail naming the drift.

    `claude plugin update` and the other runtime updaters skip a plugin whose
    version has not changed, so a manifest left behind at the old number keeps
    that runtime's users on the old files -- the failure mode in #237.
    """
    distinct = sorted(set(versions.values()))
    if len(distinct) != 1:
        detail = ", ".join(f"{name}={version}" for name, version in sorted(versions.items()))
        raise ValueError(f"manifests disagree on version: {detail}")
    return distinct[0]


def version_from_tag(tag: str) -> str:
    """Return the version a release tag names."""
    match = TAG.match(tag)
    if not match:
        raise ValueError(f"tag {tag!r} is not v<major>.<minor>.<patch> (optionally with a -suffix)")
    return match.group("version")


def check(tag: str, root: Path = ROOT) -> str:
    """Return the released version when `tag` and every manifest agree."""
    version = version_from_tag(tag)
    versions = manifest_versions(root)
    declared = declared_version(versions)
    if version != declared:
        raise ValueError(
            f"tag {tag!r} names {version}, but the manifests declare {declared}; "
            "bump the manifests before tagging"
        )
    return declared


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, for example v0.4.1")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to check")
    args = parser.parse_args(argv)
    try:
        declared = check(args.tag, args.root)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.tag} matches version {declared} in {len(MANIFESTS)} manifests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
