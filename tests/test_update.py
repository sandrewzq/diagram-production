#!/usr/bin/env python3
"""Offline regression test for the update check: no network is ever touched."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_update.py"


def load(cache_root: Path):
    """Load the script with its cache directory pointed at a scratch root."""
    os.environ["XDG_CACHE_HOME"] = str(cache_root)
    spec = importlib.util.spec_from_file_location("check_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(module) -> None:
    """Any attempt to reach the network fails loudly, proving the test never depends on it."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("the update check reached the network")

    module.fetch_json = refuse


def seed(module, tag: str, age: float = 0.0, notified: str = "") -> None:
    module.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    module.CACHE_FILE.write_text(json.dumps({
        "repo": module.DEFAULT_REPO, "remote": tag, "url": "https://example.invalid",
        "checked_at": time.time() - age, "notified": notified,
    }), encoding="utf-8")


def run(module, *argv: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main(list(argv))
    if code != 0:
        raise SystemExit(f"update check should always exit 0, got {code}")
    return out.getvalue()


def check_versions(module) -> None:
    cases = [
        ("v1.0.1", "1.0.0", True), ("v1.0.0", "1.0.0", False),
        ("v1.0.10", "1.0.9", True), ("v1.0.0", "1.0.0-rc1", True),
        ("v1.0.0-rc2", "1.0.0-rc1", True), ("v1.0", "1.0.0", False),
        ("v2.0.0", "1.99.99", True), ("1.0.0", "2.0.0", False),
    ]
    for remote, local, expected in cases:
        got = module.is_newer(remote, local)
        if got is not expected:
            raise SystemExit(f"is_newer({remote!r}, {local!r}) should be {expected}, got {got}")


def check_silent_when_current(module) -> None:
    seed(module, "v0.0.1")
    offline(module)
    if run(module):
        raise SystemExit("a fresh cache with an older upstream tag must stay silent")


def check_reports_newer(module) -> None:
    seed(module, "v9.9.9")
    offline(module)
    output = run(module)
    if "9.9.9" not in output:
        raise SystemExit(f"a newer upstream tag must be reported, got {output!r}")
    if "pull --ff-only" not in output:
        raise SystemExit(f"the report should name a non-destructive upgrade, got {output!r}")
    if "nothing changes until you run it" not in output:
        raise SystemExit("the report should state that nothing is applied automatically")
    if run(module):
        raise SystemExit("the same upstream tag must not be reported twice")
    if "9.9.9" not in run(module, "--always"):
        raise SystemExit("--always should repeat the report")


def check_quiet_and_optout(module) -> None:
    seed(module, "v9.9.9")
    offline(module)
    if run(module, "--quiet"):
        raise SystemExit("--quiet must print nothing")
    os.environ["DIAGRAM_PRODUCTION_NO_UPDATE_CHECK"] = "1"
    try:
        if run(module, "--always"):
            raise SystemExit("DIAGRAM_PRODUCTION_NO_UPDATE_CHECK must disable the check")
    finally:
        os.environ.pop("DIAGRAM_PRODUCTION_NO_UPDATE_CHECK", None)


def check_expiry_triggers_network(module) -> None:
    seed(module, "v9.9.9", age=module.DEFAULT_TTL + 60)
    offline(module)
    try:
        run(module)
    except AssertionError:
        return                                  # the expired entry correctly forced a fresh check
    raise SystemExit("an expired cache entry should trigger a network check")


def check_offline_after_expiry(module) -> None:
    seed(module, "v9.9.9", age=module.DEFAULT_TTL + 60)
    module.fetch_json = lambda *_args, **_kwargs: None    # the host answers nothing
    if run(module):
        raise SystemExit("an expired entry plus an unreachable host must stay silent")


def check_non_git_hint(module) -> None:
    """A copy that is not a git checkout must be told to download, not to pull."""
    seed(module, "v9.9.9")
    offline(module)
    os.environ["DIAGRAM_PRODUCTION_DIR"] = str(module.CACHE_DIR.parent)
    try:
        output = run(module, "--always")
    finally:
        os.environ.pop("DIAGRAM_PRODUCTION_DIR", None)
    if "pull --ff-only" in output:
        raise SystemExit(f"a non-git copy should not be told to pull, got {output!r}")
    if "download" not in output:
        raise SystemExit(f"a non-git copy should be told to download, got {output!r}")


def check_local_version(module) -> None:
    value = module.local_version()
    if not value or value == "0.0.0":
        raise SystemExit(f"SKILL.md metadata.version should be readable, got {value!r}")


def main() -> int:
    os.environ.pop("DIAGRAM_PRODUCTION_NO_UPDATE_CHECK", None)
    with tempfile.TemporaryDirectory(prefix="diagram-update-") as directory:
        cache_root = Path(directory)
        for step in (check_versions, check_local_version, check_silent_when_current,
                     check_reports_newer, check_quiet_and_optout, check_non_git_hint,
                     check_expiry_triggers_network, check_offline_after_expiry):
            module = load(cache_root)          # reload so each case starts from a clean cache path
            module.CACHE_FILE.unlink(missing_ok=True)
            step(module)
    print("update-check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
