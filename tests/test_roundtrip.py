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


def upward_edge_clears_boxes(work: Path) -> None:
    """A return edge between two stacked nodes must not be drawn through either box."""
    import re
    spec = work / "upward.json"
    spec.write_text(json.dumps({
        "type": "swimlane", "title": "Upward edge",
        "lanes": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "columns": [
            {"lane": "a", "nodes": [{"id": "back", "title": "Return factor", "column": 1}]},
            {"lane": "b", "nodes": [{"id": "verify", "title": "Verify", "column": 1}]},
        ],
        "edges": [{"from": "verify", "to": "back", "label": "return", "kind": "return", "dash": True}],
    }), encoding="utf-8")
    html = work / "upward.html"
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(html), "--check")
    markup = html.read_text(encoding="utf-8")
    boxes = [(float(m[1]), float(m[2]), float(m[1]) + float(m[3]), float(m[2]) + float(m[4]))
             for m in re.finditer(r'class="node [^"]*" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', markup)]
    path = re.search(r'<path class="edge"[^>]*\sd="([^"]+)"', markup)
    if not path or len(boxes) < 2:
        raise SystemExit("upward edge case did not render a node-to-node edge")
    points: list[tuple[float, float]] = []
    cursor = (0.0, 0.0)
    for command, raw in re.findall(r'([MLHVZmlhvz])([^MLHVZmlhvz]*)', path.group(1)):
        values = [float(value) for value in re.findall(r'-?\d+\.?\d*', raw)]
        if command in "Mm":
            for i in range(0, len(values) - 1, 2):
                cursor = (values[i], values[i + 1])
                points.append(cursor)
        elif command in "Ll":
            for i in range(0, len(values) - 1, 2):
                cursor = (values[i], values[i + 1])
                points.append(cursor)
        elif command in "Hh":
            for value in values:
                cursor = (value, cursor[1])
                points.append(cursor)
        elif command in "Vv":
            for value in values:
                cursor = (cursor[0], value)
                points.append(cursor)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        for x0, y0, x1, y1 in boxes:
            if abs(ay - by) < 0.5 and y0 + 2 < ay < y1 - 2 and min(ax, bx) < x1 - 2 and max(ax, bx) > x0 + 2:
                raise SystemExit(f"upward edge runs through a node box at y={ay}")
            if abs(ax - bx) < 0.5 and x0 + 2 < ax < x1 - 2 and min(ay, by) < y1 - 2 and max(ay, by) > y0 + 2:
                raise SystemExit(f"upward edge runs through a node box at x={ax}")


def clipping_edge_is_reported(work: Path) -> None:
    """A route that cuts through an endpoint box must be reported by --check."""
    spec = work / "clipping.json"
    spec.write_text(json.dumps({
        "type": "swimlane", "title": "Clipping route",
        "lanes": [{"id": "a", "name": "A", "y": 0, "height": 700}],
        "nodes": [
            {"id": "top", "column": 0, "lane": "a", "title": "Top", "x": 100, "y": 100},
            {"id": "low", "column": 0, "lane": "a", "title": "Low", "x": 100, "y": 400},
        ],
        "edges": [{"from": "low", "to": "top", "route": [[220, 400], [220, 130], [220, 100]]}],
    }), encoding="utf-8")
    result = subprocess.run([PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(work / "clipping.html"), "--check"],
                            text=True, capture_output=True)
    if "edge-through-node" not in result.stdout:
        raise SystemExit(f"a route through an endpoint box should be reported, got {result.stdout!r}")


def shared_port_is_avoided(work: Path) -> None:
    """An out-edge must not leave from the port another edge enters, or the heads overlap."""
    import re
    spec = work / "shared-port.json"
    spec.write_text(json.dumps({
        "type": "swimlane", "title": "Shared port",
        "lanes": [{"id": "lanes", "name": "Upper", "y": 0, "height": 900},
                  {"id": "low", "name": "Lower", "y": 900, "height": 300}],
        "columns": [{"nodes": [
            {"id": "relay", "lane": "lanes", "title": "Relay", "x": 901, "y": 760, "width": 190, "height": 78},
            {"id": "factor", "lane": "low", "title": "Return factor", "x": 901, "y": 960, "width": 190, "height": 78},
            {"id": "gen", "lane": "lanes", "title": "Generate", "x": 1265, "y": 352, "width": 190, "height": 78},
        ]}],
        "edges": [
            {"from": "relay", "to": "factor", "label": "return"},
            {"from": "factor", "to": "gen", "label": "factor", "dash": True},
        ],
    }), encoding="utf-8")
    html = work / "shared-port.html"
    run(PYTHON, str(ROOT / "scripts/diagram.py"), str(spec), "-o", str(html), "--check")
    markup = html.read_text(encoding="utf-8")
    starts = []
    for path_data in re.findall(r'<path class="edge"[^>]*\sd="([^"]+)"', markup):
        first = re.match(r"M ([\d.]+) ([\d.]+)", path_data)
        last = re.findall(r"(-?\d+\.?\d*) (-?\d+\.?\d*)", path_data)[-1]
        starts.append(((float(first.group(1)), float(first.group(2))), (float(last[0]), float(last[1]))))
    if len(starts) < 2:
        raise SystemExit("shared port case did not render two edges")
    (in_start, in_end), (out_start, out_end) = starts
    if in_end == out_start:
        raise SystemExit(f"the out-edge still departs from the port the in-edge enters: {out_start}")
    if out_start[0] < 1090.5 or out_start[1] < 998.5 or out_start[1] > 999.5:
        raise SystemExit(f"the out-edge should take the right port (1091, 999), got {out_start}")


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
        upward_edge_clears_boxes(work)
        clipping_edge_is_reported(work)
        shared_port_is_avoided(work)
    print("roundtrip: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
