#!/usr/bin/env python3
"""Dependency-free regression test for render -> extract -> render."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CLASSLESS_SVG = """<html><body><h1>Unclassified figure</h1>
<svg viewBox="0 0 400 200"><rect x="10" y="10" width="90" height="40"/><text x="20" y="40">A</text></svg>
</body></html>
"""


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=True)
    return result.stdout


def roundtrip(work: Path, example: str) -> None:
    source = work / f"{Path(example).stem}-source.html"
    spec = work / f"{Path(example).stem}-extracted.json"
    rebuilt = work / f"{Path(example).stem}-rebuilt.html"
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(ROOT / "examples" / example), "-o", str(source), "--check")
    run(PYTHON, str(ROOT / "scripts/extract_svg.py"), str(source), "-o", str(spec))
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(rebuilt), "--check")
    result = run(PYTHON, str(ROOT / "scripts/verify_render.py"), str(source), str(rebuilt))
    if "result: MATCH" not in result:
        raise SystemExit(f"{example}: {result}")


def unrecognized(work: Path) -> None:
    source = work / "classless.html"
    spec = work / "classless.json"
    source.write_text(CLASSLESS_SVG, encoding="utf-8")
    result = subprocess.run([PYTHON, str(ROOT / "scripts/extract_svg.py"), str(source), "-o", str(spec)],
                            text=True, capture_output=True)
    if result.returncode != 2:
        raise SystemExit(f"classless extraction should exit 2, got {result.returncode}")
    if "incomplete" not in result.stdout:
        raise SystemExit(f"classless extraction should warn, got {result.stdout!r}")
    extracted = json.loads(spec.read_text(encoding="utf-8"))
    if extracted.get("type") != "unknown":
        raise SystemExit(f"classless extraction should record type unknown, got {extracted.get('type')!r}")
    if not extracted.get("_extraction_warnings"):
        raise SystemExit("classless extraction should record _extraction_warnings")


LEGACY_EXPECTATION = {"legacy-swimlane.json": True, "data-flow.json": False, "system-map.json": False}


def empty_spec(work: Path) -> None:
    spec = work / "empty.json"
    spec.write_text('{}', encoding="utf-8")
    result = subprocess.run([PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(work / "empty.html"), "--check"],
                            text=True, capture_output=True)
    if result.returncode != 2:
        raise SystemExit(f"empty spec should exit 2, got {result.returncode}")
    if "defines no diagram elements" not in result.stdout:
        raise SystemExit(f"empty spec should warn, got {result.stdout!r}")


def adjacent_blocks(work: Path) -> None:
    """A decision without its own sub text must not inherit the next node's sub text."""
    spec = work / "adjacent.json"
    spec.write_text(json.dumps({
        "type": "swimlane", "title": "Adjacent blocks",
        "lanes": [{"id": "people", "name": "People"}],
        "nodes": [
            {"id": "ask", "column": 0, "lane": "people", "kind": "decision", "title": "Ready?"},
            {"id": "next", "column": 1, "lane": "people", "kind": "process", "title": "Carry on", "sub": "Borrowed wording"},
        ],
        "edges": [{"from": "ask", "to": "next", "label": "yes"}],
    }), encoding="utf-8")
    source = work / "adjacent-source.html"
    extracted = work / "adjacent-extracted.json"
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(source), "--check")
    run(PYTHON, str(ROOT / "scripts/extract_svg.py"), str(source), "-o", str(extracted))
    nodes = {node.get("title"): node for column in json.loads(extracted.read_text(encoding="utf-8")).get("columns", [])
             for node in column.get("nodes", [])}
    if nodes.get("Ready?", {}).get("sub"):
        raise SystemExit(f"decision without sub inherited {nodes['Ready?']['sub']!r} from a later node")
    if nodes.get("Carry on", {}).get("sub") != "Borrowed wording":
        raise SystemExit(f"next node lost its own sub, got {nodes.get('Carry on', {}).get('sub')!r}")


def unnamed_lane(work: Path) -> None:
    """A lane with no visible name must not adopt the next lane's title."""
    spec = work / "lanes.json"
    spec.write_text(json.dumps({
        "type": "swimlane", "title": "Lane names",
        "lanes": [{"id": "a", "name": ""}, {"id": "b", "name": "Second lane", "sub": "with sub"}],
        "nodes": [{"id": "n1", "column": 0, "lane": "a", "title": "One"},
                  {"id": "n2", "column": 1, "lane": "b", "title": "Two"}],
        "edges": [{"from": "n1", "to": "n2"}],
    }), encoding="utf-8")
    source = work / "lanes-source.html"
    extracted = work / "lanes-extracted.json"
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(source), "--check")
    run(PYTHON, str(ROOT / "scripts/extract_svg.py"), str(source), "-o", str(extracted))
    lanes = json.loads(extracted.read_text(encoding="utf-8"))["lanes"]
    if lanes[0].get("name"):
        raise SystemExit(f"unnamed lane inherited {lanes[0]['name']!r} from the next lane")
    if lanes[1].get("name") != "Second lane":
        raise SystemExit(f"second lane lost its title, got {lanes[1].get('name')!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="diagram-roundtrip-") as directory:
        work = Path(directory)
        for example in sorted(path.name for path in (ROOT / "examples").glob("*.json")):
            roundtrip(work, example)
            extracted = json.loads((work / f"{Path(example).stem}-extracted.json").read_text(encoding="utf-8"))
            expected = LEGACY_EXPECTATION.get(example)
            if expected is not None and bool(extracted.get("_legacy_swimlane")) is not expected:
                raise SystemExit(f"{example}: _legacy_swimlane should be {expected}, got {extracted.get('_legacy_swimlane')}")
        unrecognized(work)
        empty_spec(work)
        adjacent_blocks(work)
        unnamed_lane(work)
    print("roundtrip: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
