#!/usr/bin/env python3
"""Compare the visible structure of an original diagram and a render.

Both the public CLI and the legacy swimlane CLI are accepted:

  verify_render.py source.html rendered.html
  verify_render.py source.html --spec spec.json --html rendered.html
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def text_value(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()


def attr(attrs: str, name: str, default: float = 0.0) -> float:
    match = re.search(r'(?<![\w-])' + re.escape(name) + r'="([^\"]*)"', attrs)
    try:
        return float(match.group(1)) if match else default
    except ValueError:
        return default


def category(tag: str, classes: str) -> str:
    tokens = set(classes.split())
    if tag == "rect" and ("lane" in tokens or "lane-band" in tokens or "band" in tokens):
        return "band"
    if tag == "rect" and "node" in tokens:
        return "node"
    if tag == "rect" and "actor" in tokens:
        return "actor"
    if tag == "rect" and "tag" in tokens:
        return "tag"
    if tag == "polygon" and "decision" in tokens:
        return "decision"
    if tag == "polygon" and ("msg-arrow" in tokens or not tokens):
        return "ignore"
    if tag == "line" and "lifeline" in tokens:
        return "lifeline"
    if tag == "line" and "msg" in tokens:
        return "msg"
    if tag == "path" and ("edge" in tokens or "arrow" in tokens):
        return "edge"
    return tag


def text_category(classes: str) -> str:
    tokens = set(classes.split())
    if "actor-t" in tokens:
        return "actor-t"
    if "lbl" in tokens:
        return "lbl"
    if "tag-t" in tokens:
        return "tag-t"
    if "lane-title" in tokens or "lane-label" in tokens:
        return "lane-title"
    if "lane-sub" in tokens:
        return "lane-sub"
    if "nd-title" in tokens or "node-title" in tokens or "decision-title" in tokens:
        return "node-title"
    if "nd-sub" in tokens or "node-sub" in tokens or "decision-sub" in tokens:
        return "node-sub"
    if "nd-meta" in tokens or "nd-tag" in tokens or "node-footer" in tokens:
        return "node-footer"
    if "flow-label" in tokens or "edge-label" in tokens:
        return "edge-label"
    return "text"


def fingerprint(svg: str) -> tuple[Counter, dict[tuple, list[tuple[float, float]]]]:
    counts: Counter = Counter()
    coords: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for match in re.finditer(r'<(rect|polygon|path|line)\b([^>]*)/?>', svg, re.I):
        tag, attrs = match.group(1).lower(), match.group(2)
        classes = re.search(r'class="([^"]*)"', attrs)
        kind = category(tag, classes.group(1) if classes else "")
        if kind in {"path", "ignore"}:
            continue
        key = (kind,)
        counts[key] += 1
        x = attr(attrs, "x") if tag != "line" else attr(attrs, "x1")
        y = attr(attrs, "y") if tag != "line" else attr(attrs, "y1")
        coords[key].append((x, y))
    for match in re.finditer(r'<text\b([^>]*)>(.*?)</text>', svg, re.S | re.I):
        attrs, body = match.groups()
        classes = re.search(r'class="([^"]*)"', attrs)
        kind = text_category(classes.group(1) if classes else "")
        value = text_value(body)
        key = ("text", kind, value)
        counts[key] += 1
        coords[key].append((attr(attrs, "x"), attr(attrs, "y")))
    return counts, coords


def pick_svg(text: str, index: int = 0, number: str | None = None) -> str:
    if number is not None:
        for section in re.findall(r"<section\b.*?</section>", text, re.S | re.I):
            hit = re.search(r'<(?:span|div)\b[^>]*class="[^"]*(?:num|figure-number)[^"]*"[^>]*>\s*0*([0-9]+)', section, re.I)
            if hit and str(int(hit.group(1))) == str(int(number)):
                svg = re.search(r"<svg\b.*?</svg>", section, re.S | re.I)
                if svg:
                    return svg.group(0)
    svgs = re.findall(r"<svg\b.*?</svg>", text, re.S | re.I)
    if index < 0 or index >= len(svgs):
        raise ValueError(f"svg index out of range: {index} (found {len(svgs)})")
    return svgs[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare original and rendered diagram structure")
    parser.add_argument("source", type=Path)
    parser.add_argument("rendered", type=Path, nargs="?")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--svg-index", type=int, default=0, help="source SVG index")
    parser.add_argument("--rendered-svg-index", type=int, default=None, help="rendered SVG index; defaults to source index or 0 when only one exists")
    parser.add_argument("--tolerance", type=float, default=1.0)
    args = parser.parse_args()
    rendered_path = args.rendered or args.html
    if rendered_path is None:
        parser.error("rendered path or --html is required")
    number = None
    if args.spec:
        raw_number = json.loads(args.spec.read_text(encoding="utf-8")).get("number")
        number = str(raw_number) if raw_number is not None else None
    source_svg = pick_svg(args.source.read_text(encoding="utf-8"), args.svg_index, number)
    rendered_text = rendered_path.read_text(encoding="utf-8")
    rendered_svgs = re.findall(r"<svg\b.*?</svg>", rendered_text, re.S | re.I)
    rendered_index = args.rendered_svg_index if args.rendered_svg_index is not None else (args.svg_index if len(rendered_svgs) > args.svg_index else 0)
    rendered_svg = pick_svg(rendered_text, rendered_index)
    source_counts, source_coords = fingerprint(source_svg)
    rendered_counts, rendered_coords = fingerprint(rendered_svg)
    missing = [f"{key}: {count}" for key, count in (source_counts - rendered_counts).items()]
    extra = [f"{key}: {count}" for key, count in (rendered_counts - source_counts).items()]
    worst = 0.0
    shifts = []
    for key in set(source_coords) & set(rendered_coords):
        for before, after in zip(sorted(source_coords[key]), sorted(rendered_coords[key])):
            delta = max(abs(before[0] - after[0]), abs(before[1] - after[1]))
            worst = max(worst, delta)
            if delta > args.tolerance:
                shifts.append(f"{key}: {delta:.1f}px")
    print(f"elements: source {sum(source_counts.values())} / rendered {sum(rendered_counts.values())}")
    print(f"maximum coordinate drift: {worst:.2f}px")
    if missing:
        print("missing:"); print("\n".join(f"  - {item}" for item in missing[:20]))
    if extra:
        print("extra:"); print("\n".join(f"  + {item}" for item in extra[:20]))
    if shifts:
        print(f"coordinate drift > tolerance ({len(shifts)} items):"); print("\n".join(f"  ~ {item}" for item in shifts[:20]))
    ok = not missing and not extra and worst <= args.tolerance
    print("result: " + ("MATCH" if ok else "DIFFERENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
