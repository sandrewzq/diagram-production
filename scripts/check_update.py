#!/usr/bin/env python3
"""Report whether a newer release exists upstream. Never modifies anything."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "diagram-production"
CACHE_FILE = CACHE_DIR / "update-check.json"
RELEASES_URL = "https://api.github.com/repos/{repo}/releases/latest"
TAGS_URL = "https://api.github.com/repos/{repo}/tags"
DEFAULT_REPO = "sandrewzq/diagram-production"
DEFAULT_TTL = 86400
NETWORK_TIMEOUT = 4.0


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def local_version() -> str:
    """The version shipped with this checkout: SKILL.md metadata first, VERSION file second."""
    skill = ROOT / "SKILL.md"
    if skill.is_file():
        head = skill.read_text(encoding="utf-8")[:2000]
        match = re.search(r"^\s*version:\s*[\"']?([0-9][0-9A-Za-z.\-+]*)[\"']?\s*$", head, re.M)
        if match:
            return match.group(1)
    version_file = ROOT / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


def version_key(version: str) -> tuple:
    """(numeric core, released flag, prerelease chunks); a plain release outranks a prerelease."""
    text = version.strip().lstrip("vV")
    match = re.match(r"^([0-9]+(?:\.[0-9]+)*)([-+].*)?$", text)
    if match:
        core = tuple(int(part) for part in match.group(1).split("."))
        suffix = match.group(2)
        if not suffix:
            return core, 1, ()
        chunks = tuple((1, int(item), "") if item.isdigit() else (0, 0, item)
                       for item in re.split(r"[.\-+]", suffix.lstrip("-+")) if item)
        return core, 0, chunks
    chunks = tuple((1, int(item), "") if item.isdigit() else (0, 0, item)
                   for item in re.split(r"[.\-+]", text) if item)
    return (), 0, chunks


def is_newer(remote: str, local: str) -> bool:
    remote_core, remote_released, remote_pre = version_key(remote)
    local_core, local_released, local_pre = version_key(local)
    width = max(len(remote_core), len(local_core))
    pad = lambda core: core + (0,) * (width - len(core))
    return (pad(remote_core), remote_released, remote_pre) > (pad(local_core), local_released, local_pre)


def read_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_cache(payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def fetch_json(url: str) -> dict | list | None:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "diagram-production-update-check",
    })
    try:
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None


def remote_version(repo: str) -> tuple[str, str] | None:
    """Latest published tag and its page, or None when the network says nothing usable."""
    release = fetch_json(RELEASES_URL.format(repo=repo))
    if isinstance(release, dict):
        tag = str(release.get("tag_name") or "").strip()
        if tag and not release.get("draft"):
            return tag, str(release.get("html_url") or "")
    tags = fetch_json(TAGS_URL.format(repo=repo))
    if isinstance(tags, list):
        for entry in tags:
            tag = str(entry.get("name") or "").strip() if isinstance(entry, dict) else ""
            if tag and re.match(r"^v?\d", tag):
                return tag, f"https://github.com/{repo}/releases/tag/{tag}"
    return None


def cached_remote(cache: dict, ttl: int, repo: str) -> tuple[str, str] | None:
    """Fresh value from the cache, or a fresh-enough value even if this call cannot reach GitHub."""
    if cache.get("repo") != repo:
        return None
    checked = cache.get("checked_at")
    tag = cache.get("remote")
    if not isinstance(checked, (int, float)) or not tag:
        return None
    if time.time() - checked > ttl:
        return None
    return str(tag), str(cache.get("url") or "")


def resolve(ttl: int, repo: str) -> tuple[str, str] | None:
    cache = read_cache()
    fresh = cached_remote(cache, ttl, repo)
    if fresh:
        return fresh
    fetched = remote_version(repo)
    if fetched:
        write_cache({"repo": repo, "remote": fetched[0], "url": fetched[1],
                     "checked_at": time.time(), "notified": cache.get("notified", "")})
        return fetched
    # Stale knowledge is not knowledge: an expired entry plus an unreachable host stays silent.
    return None


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv or "-q" in argv
    always = "--always" in argv
    ttl = DEFAULT_TTL
    repo = os.environ.get("DIAGRAM_PRODUCTION_REPO", DEFAULT_REPO)
    for argument in argv:
        if argument.startswith("--ttl="):
            try:
                ttl = max(0, int(argument.split("=", 1)[1]))
            except ValueError:
                pass
        elif argument.startswith("--repo="):
            repo = argument.split("=", 1)[1].strip() or DEFAULT_REPO
    if "--help" in argv or "-h" in argv:
        print("usage: check_update.py [--quiet] [--always] [--ttl=SECONDS] [--repo=OWNER/NAME]")
        print("Reports a newer upstream release. Read-only: it never installs, pulls, or edits files.")
        return 0
    if env_flag("DIAGRAM_PRODUCTION_NO_UPDATE_CHECK"):
        return 0

    local = local_version()
    latest = resolve(ttl, repo)
    if not latest:
        return 0
    tag, url = latest
    if not is_newer(tag, local):
        return 0

    cache = read_cache()
    already = str(cache.get("notified") or "") == tag
    if quiet or (already and not always):
        return 0
    write_cache({**cache, "repo": repo, "notified": tag})
    where = Path(os.environ.get("DIAGRAM_PRODUCTION_DIR") or ROOT)
    print(f"diagram-production {tag} is available upstream; this copy is {local}.")
    print(f"  review:  {url or f'https://github.com/{repo}/releases'}")
    if (where / ".git").exists():
        print(f"  upgrade: git -C {where} pull --ff-only")
    else:
        print(f"  upgrade: download {url or f'https://github.com/{repo}/releases'} and replace this copy")
    print("  nothing changes until you run it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
