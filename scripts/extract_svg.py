#!/usr/bin/env python3
"""Extract a generic HTML/SVG diagram into a semantic JSON spec.

This is intentionally conservative: it preserves visible text, approximate
lanes, node geometry, and orthogonal edge routes. It does not infer business
meaning that is absent from the source artwork.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

NUMBER = r"-?(?:\d+\.?\d*|\.\d+)"


def attr(tag: str, name: str, default: str = "") -> str:
    match = re.search(r'(?<![\w-])' + re.escape(name) + r'="([^"]*)"', tag)
    return match.group(1) if match else default


def text_value(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def text_in(block: str, classes: tuple[str, ...]) -> str:
    for cls in classes:
        match = re.search(r'<text[^>]*class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>(.*?)</text>', block, re.S)
        if match:
            value = text_value(match.group(1))
            if value:
                return value
    return ""


def footer_lines(block: str) -> list[tuple[str, float | None]]:
    """All `node-footer` text lines of one node block, ordered top to bottom."""
    found = []
    for match in re.finditer(r'<text[^>]*class="[^"]*\bnode-footer\b[^"]*"[^>]*>(.*?)</text>', block, re.S):
        value = text_value(match.group(1))
        if not value:
            continue
        raw_y = attr(match.group(0), "y", "")
        found.append((value, float(raw_y) if raw_y != "" else None))
    return sorted(found, key=lambda item: (item[1] is None, item[1] or 0.0))


def text_class_in(block: str, classes: tuple[str, ...]) -> str:
    for cls in classes:
        match = re.search(r'<text[^>]*class="([^"]*\b' + re.escape(cls) + r'[^\"]*)"[^>]*>', block, re.S)
        if match:
            tokens = match.group(1).split()
            base = set(classes) | {"node-footer", "nd-meta", "nd-tag"}
            return next((token for token in reversed(tokens) if token not in base), "")
    return ""


def text_y_in(block: str, classes: tuple[str, ...]) -> float | None:
    for cls in classes:
        match = re.search(r'<text[^>]*class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>', block, re.S)
        if match:
            value = attr(match.group(0), "y", "")
            return float(value) if value != "" else None
    return None


def points_from_path(path: str) -> list[list[float]]:
    tokens = re.findall(r'[MLHVZmlhvz]|' + NUMBER, path)
    points: list[list[float]] = []
    x = y = 0.0
    command = "M"
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            continue
        if command in ("M", "L") and i + 1 < len(tokens):
            x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
        elif command == "H":
            x = float(tokens[i]); i += 1
        elif command == "V":
            y = float(tokens[i]); i += 1
        elif command == "m" and i + 1 < len(tokens):
            x += float(tokens[i]); y += float(tokens[i + 1]); i += 2
        elif command == "l" and i + 1 < len(tokens):
            x += float(tokens[i]); y += float(tokens[i + 1]); i += 2
        elif command == "h":
            x += float(tokens[i]); i += 1
        elif command == "v":
            y += float(tokens[i]); i += 1
        else:
            i += 1
            continue
        if not points or points[-1] != [x, y]:
            points.append([x, y])
    return points


def box_distance(point: tuple[float, float], box: dict) -> float:
    x, y = point
    cx = min(max(x, box["x"]), box["x"] + box["width"])
    cy = min(max(y, box["y"]), box["y"] + box["height"])
    return ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5


def _sequence_id(title: str, used: dict[str, int]) -> str:
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", title)[:24] or "participant"
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else f"{base}{used[base]}"


def extract_sequence(svg: str, title: str = "Extracted sequence", metadata: dict | None = None) -> dict:
    """Extract the stable sequence semantics from actor/lifeline/message SVGs.

    Arrow polygons are deliberately secondary: historical files sometimes contain a
    malformed polygon while the message line itself still has valid endpoints.
    """
    metadata = metadata or {}
    svg_tag_match = re.search(r"<svg\b[^>]*>", svg, re.I)
    viewbox = attr(svg_tag_match.group(0), "viewBox", "0 0 1200 800") if svg_tag_match else "0 0 1200 800"
    numbers = [float(value) for value in viewbox.split()]
    width, height = (numbers[2], numbers[3]) if len(numbers) >= 4 else (1200.0, 800.0)
    text_items = []
    for match in re.finditer(r'<text\b([^>]*)>(.*?)</text>', svg, re.S | re.I):
        attrs, body = match.groups()
        classes = attr(re.search(r'<text\b[^>]*>', match.group(0), re.I).group(0), "class", "")
        text_items.append({"x": float(attr(match.group(0), "x", 0)), "y": float(attr(match.group(0), "y", 0)),
                           "class": classes, "value": text_value(body)})

    actors = []
    for match in re.finditer(r'<rect\b[^>]*class="([^"]*\bactor\b[^"]*)"[^>]*>', svg, re.I):
        tag = match.group(0)
        x, y = float(attr(tag, "x", 0)), float(attr(tag, "y", 0))
        w, h = float(attr(tag, "width", 0)), float(attr(tag, "height", 0))
        cx, cy = x + w / 2, y + h / 2
        candidates = [item for item in text_items if "actor-t" in item["class"]]
        text = min(candidates, key=lambda item: abs(item["x"] - cx) + abs(item["y"] - cy), default={"value": ""})["value"]
        classes = attr(tag, "class").split()
        visual = next((token for token in classes if token not in {"actor"}), "actor")
        actors.append({"x": x, "y": y, "width": w, "height": h, "w": w, "h": h,
                       "title": text or f"Participant {len(actors) + 1}", "cls": visual})
    actors.sort(key=lambda item: (item["x"], item["y"]))
    used: dict[str, int] = {}
    for actor in actors:
        actor["id"] = _sequence_id(actor["title"], used)
    def participant_for_x(x: float) -> dict | None:
        return min(actors, key=lambda item: abs((item["x"] + item["width"] / 2) - x)) if actors else None

    lifelines = []
    for match in re.finditer(r'<line\b[^>]*class="[^"]*\blifeline\b[^"]*"[^>]*>', svg, re.I):
        tag = match.group(0)
        lifelines.append((float(attr(tag, "x1", 0)), float(attr(tag, "y1", 0)), float(attr(tag, "x2", 0)), float(attr(tag, "y2", 0))))
    lifeline_top = min((item[1] for item in lifelines), default=max((actor["y"] + actor["height"] for actor in actors), default=60) + 18)
    lifeline_bottom = max((item[3] for item in lifelines), default=height - 20)

    messages = []
    for match in re.finditer(r'<line\b[^>]*class="([^"]*\bmsg\b[^"]*)"[^>]*>', svg, re.I):
        tag, classes = match.group(0), match.group(1)
        x1, y1, x2, y2 = float(attr(tag, "x1", 0)), float(attr(tag, "y1", 0)), float(attr(tag, "x2", 0)), float(attr(tag, "y2", 0))
        if abs(y1 - y2) > 1.0:
            continue
        source, target = participant_for_x(x1), participant_for_x(x2)
        messages.append({"x1": x1, "x2": x2, "y": y1, "from": source["id"] if source else "", "to": target["id"] if target else "",
                         "kind": "response" if "ret" in classes.split() else "flow",
                         **({"color": attr(tag, "stroke", "")} if attr(tag, "stroke", "") else {})})
    messages.sort(key=lambda item: item["y"])
    labels = [item for item in text_items if "lbl" in item["class"] or "flow-label" in item["class"]]
    for label in labels:
        if not messages:
            break
        nearest = min(messages, key=lambda item: abs(item["y"] - label["y"]))
        nearest["label"] = label["value"]
        nearest["label_at"] = [label["x"], label["y"]]
    for message in messages:
        if message.get("color") == "#9a3412":
            message["alert"] = True

    annotations = []
    for match in re.finditer(r'<rect\b[^>]*class="[^"]*\btag\b[^"]*"[^>]*>', svg, re.I):
        tag = match.group(0)
        x, y, w, h = float(attr(tag, "x", 0)), float(attr(tag, "y", 0)), float(attr(tag, "width", 0)), float(attr(tag, "height", 0))
        tag_candidates = [item for item in text_items if "tag-t" in item["class"] and x - 24 <= item["x"] <= x + w + 24 and y - 4 <= item["y"] <= y + h + 18]
        text = min(tag_candidates or [item for item in text_items if "tag-t" in item["class"]], key=lambda item: abs(item["x"] - x) + abs(item["y"] - (y + h)), default={"value": ""})["value"]
        annotations.append({"x": x, "y": y, "width": w, "height": h, "text": text})

    warnings = []
    for match in re.finditer(r'<polygon\b[^>]*>', svg, re.I):
        tag = match.group(0)
        classes = attr(tag, "class", "")
        if "decision" in classes:
            continue
        points = [float(value) for value in re.findall(NUMBER, attr(tag, "points", ""))]
        if len(points) < 6:
            continue
        xs, ys = points[0::2], points[1::2]
        if min(xs) < 0 or max(xs) > width or min(ys) < 0 or max(ys) > height:
            warnings.append("legacy sequence arrow polygon outside viewBox was ignored")

    return {"type": "sequence", "title": metadata.get("title", title), "subtitle": metadata.get("subtitle", "Extracted from existing SVG/HTML."),
            "participants": actors, "messages": messages, "annotations": annotations,
            "lifeline_top": lifeline_top, "lifeline_bottom": lifeline_bottom,
            "_viewbox": [width, height], "_legacy_extracted": True, "_legacy_sequence": True,
            "_extraction_warnings": sorted(set(warnings))}


def extract_svg(svg: str, title: str = "Extracted diagram", metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    if re.search(r'<rect\b[^>]*class="[^"]*\bactor\b', svg, re.I) and re.search(r'<line\b[^>]*class="[^"]*\bmsg\b', svg, re.I):
        return extract_sequence(svg, title, metadata)
    viewbox = attr(re.search(r"<svg\b[^>]*>", svg).group(0), "viewBox", "0 0 1200 800")
    numbers = [float(value) for value in viewbox.split()]
    lanes = []
    for match in re.finditer(r'<rect\b[^>]*class="([^"]*(?:lane|band)[^"]*)"[^>]*>', svg, re.I):
        tag = match.group(0)
        classes = attr(tag, "class").split()
        style = next((token for token in classes if token not in {"lane", "lane-band", "band"}), "")
        lane_id = re.sub(r"[^A-Za-z0-9_-]", "", attr(tag, "data-lane", "")) or style or f"lane{len(lanes) + 1}"
        y, height = float(attr(tag, "y", 0)), float(attr(tag, "height", 0))
        following = svg[match.end():match.end() + 1200]
        stop = re.search(r'<(?:rect|polygon|path)\b', following)
        head = following[:stop.start()] if stop else following
        lanes.append({"id": lane_id, "name": text_in(head, ("lane-title", "lane-label")),
                      "sub": text_in(head, ("lane-sub",)), "style": style, "_y": y, "_height": height,
                      "_x": float(attr(tag, "x", 0))})

    def lane_for(y: float) -> str | None:
        for lane in lanes:
            if lane["_y"] - 1 <= y <= lane["_y"] + lane["_height"] + 1:
                return lane["id"]
        return lanes[0]["id"] if lanes else None

    raw_nodes = []
    for match in re.finditer(r'<rect\b[^>]*class="([^"]*\bnode\b[^"]*)"[^>]*>', svg, re.I):
        tag = match.group(0)
        x, y = float(attr(tag, "x", 0)), float(attr(tag, "y", 0))
        width, height = float(attr(tag, "width", 0)), float(attr(tag, "height", 0))
        following = svg[match.end():match.end() + 1000]
        stop = re.search(r'<(?:rect|polygon|path)\b', following)
        block = following[:stop.start()] if stop else following
        classes = attr(tag, "class")
        kind = "external" if ("external" in classes or "ext" in classes) else "process"
        node = {"x": x, "y": y, "width": width, "height": height, "w": width, "h": height,
                          "lane": lane_for(y + height / 2), "kind": kind,
                          "title": text_in(block, ("node-title", "nd-title")),
                          "sub": text_in(block, ("node-sub", "nd-sub")),
                          "meta": "", "tag": ""}
        meta_only, tag_only = text_in(block, ("nd-meta",)), text_in(block, ("nd-tag",))
        footers = footer_lines(block)
        if meta_only or tag_only:
            node["meta"], node["tag"] = meta_only, tag_only
        elif len(footers) >= 2:
            # The renderer draws `meta` above `tag` as two plain footer lines.
            node["meta"], node["tag"] = footers[0][0], footers[1][0]
        elif footers:
            node["meta"] = footers[0][0]
        visual_class = next((token for token in classes.split() if token in {"bpm", "ext", "external"}), "")
        if visual_class:
            node["cls"] = visual_class
        node["meta_cls"] = text_class_in(block, ("nd-meta", "node-footer"))
        node["tag_cls"] = text_class_in(block, ("nd-tag",))
        meta_y, tag_y = text_y_in(block, ("nd-meta",)), text_y_in(block, ("nd-tag",))
        if meta_y is None and not (meta_only or tag_only) and footers:
            meta_y = footers[0][1]
            if len(footers) >= 2:
                tag_y = footers[1][1]
        title_y, sub_y = text_y_in(block, ("nd-title", "node-title")), text_y_in(block, ("nd-sub", "node-sub"))
        if title_y is not None:
            node["title_y"] = title_y
        if sub_y is not None:
            node["sub_y"] = sub_y
        if meta_y is not None:
            node["meta_y"] = meta_y
        if tag_y is not None:
            node["tag_y"] = tag_y
        raw_nodes.append(node)
    for match in re.finditer(r'<polygon\b[^>]*class="[^"]*\bdecision\b[^"]*"[^>]*>', svg, re.I):
        tag = match.group(0)
        values = [float(value) for value in re.findall(NUMBER, attr(tag, "points", ""))]
        if len(values) < 8:
            continue
        xs, ys = values[0::2], values[1::2]
        x, y, width, height = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        following = svg[match.end():match.end() + 800]
        stop = re.search(r'<(?:rect|polygon|path)\b', following)
        block = following[:stop.start()] if stop else following
        decision = {"x": x, "y": y, "width": width, "height": height, "w": width, "h": height,
                    "lane": lane_for(y + height / 2), "kind": "decision",
                    "title": text_in(block, ("decision-title", "node-title")),
                    "sub": text_in(block, ("decision-sub", "node-sub"))}
        title_y, sub_y = text_y_in(block, ("decision-title", "node-title")), text_y_in(block, ("decision-sub", "node-sub"))
        if title_y is not None:
            decision["title_y"] = title_y
        if sub_y is not None:
            decision["sub_y"] = sub_y
        raw_nodes.append(decision)
    raw_nodes.sort(key=lambda item: (item["x"], item["y"]))
    used: dict[str, int] = {}
    for node in raw_nodes:
        base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", node["title"])[:18] or "node"
        used[base] = used.get(base, 0) + 1
        node["id"] = base if used[base] == 1 else f"{base}{used[base]}"

    def nearest(point: list[float]) -> dict | None:
        candidates = sorted(raw_nodes, key=lambda node: box_distance((point[0], point[1]), node))
        return candidates[0] if candidates and box_distance((point[0], point[1]), candidates[0]) <= 30 else None

    edges = []
    for match in re.finditer(r'<path\b[^>]*class="([^"]*(?:edge|arrow)[^"]*)"[^>]*>', svg, re.I):
        tag = match.group(0)
        points = points_from_path(attr(tag, "d", ""))
        if len(points) < 2:
            continue
        start, end = nearest(points[0]), nearest(points[-1])
        if not start or not end:
            continue
        edge = {"from": start["id"], "to": end["id"]}
        if len(points) > 2:
            edge["route"] = points
        edge_classes = attr(tag, "class")
        if "ext" in edge_classes:
            edge["ext"] = True
        if "dash" in edge_classes:
            edge["dash"] = True
            edge["kind"] = "dependency"
        else:
            edge["kind"] = "flow"
        edges.append(edge)

    labels = []
    for match in re.finditer(r'<text\b[^>]*class="[^"]*(?:edge-label|flow-label)[^"]*"[^>]*>.*?</text>', svg, re.S | re.I):
        tag = match.group(0)
        body = re.search(r'>((?:(?!</text>).)*)</text>', tag, re.S | re.I)
        value = text_value(body.group(1) if body else "")
        if value:
            classes = attr(tag, "class")
            labels.append((float(attr(tag, "x", 0)), float(attr(tag, "y", 0)), value, "ext" in classes, "bpm" in classes))
    assigned_edges: set[int] = set()
    attached_labels: set[int] = set()
    for label_index, (x, y, value, _, _) in enumerate(labels):
        if not edges:
            break
        def segment_score(point: tuple[float, float], a: list[float], b: list[float]) -> float:
            vx, vy = b[0] - a[0], b[1] - a[1]
            length2 = vx * vx + vy * vy
            t = max(0.0, min(1.0, ((point[0] - a[0]) * vx + (point[1] - a[1]) * vy) / length2)) if length2 else 0.0
            px, py = a[0] + t * vx, a[1] + t * vy
            endpoint_penalty = 18.0 if t < 0.12 or t > 0.88 else 0.0
            return ((point[0] - px) ** 2 + (point[1] - py) ** 2) ** 0.5 + endpoint_penalty
        def label_distance(edge: dict) -> float:
            route = edge.get("route", [])
            if not route:
                start = next(node for node in raw_nodes if node["id"] == edge["from"])
                end = next(node for node in raw_nodes if node["id"] == edge["to"])
                route = [[start["x"] + start["width"], start["y"] + start["height"] / 2],
                         [end["x"], end["y"] + end["height"] / 2]]
            return min(segment_score((x, y), a, b) for a, b in zip(route, route[1:]))
        candidates = [(label_distance(edge), index) for index, edge in enumerate(edges) if index not in assigned_edges]
        if not candidates:
            candidates = [(label_distance(edge), index) for index, edge in enumerate(edges)]
        _, nearest_index = min(candidates)
        nearest_edge = edges[nearest_index]
        assigned_edges.add(nearest_index)
        attached_labels.add(label_index)
        nearest_edge["label"] = value
        nearest_edge["label_at"] = [x, y]

    columns = {}
    for node in raw_nodes:
        column = min(columns.keys(), key=lambda value: abs(value - node["x"])) if columns and min(abs(value - node["x"]) for value in columns) < 36 else node["x"]
        columns.setdefault(column, []).append(node)
    ordered_columns = []
    for column in sorted(columns):
        ordered_columns.append({"stage": "", "nodes": []})
        for node in sorted(columns[column], key=lambda item: item["y"]):
            item = dict(node)
            item["column"] = len(ordered_columns) - 1
            ordered_columns[-1]["nodes"].append(item)
    clean_lanes = []
    for lane in lanes:
        members = [node for node in raw_nodes if node.get("lane") == lane["id"]]
        top_pad = min((node["y"] for node in members), default=lane["_y"]) - lane["_y"]
        bottom_pad = lane["_y"] + lane["_height"] - max((node["y"] + node["height"] for node in members), default=lane["_y"] + lane["_height"])
        clean_lanes.append({"id": lane["id"], "name": lane.get("name", ""), "sub": lane.get("sub", ""), "style": lane.get("style", ""),
                            "y": lane["_y"], "_h_fixed": lane["_height"], "pad_top": top_pad, "pad_bottom": bottom_pad})
    free_labels = [{"text": value, "x": x, "y": y, **({"ext": ext} if ext else {}), **({"cls": "bpm"} if bpm else {})}
                   for index, (x, y, value, ext, bpm) in enumerate(labels) if index not in attached_labels]
    title_offsets, sub_offsets, meta_bottoms, tag_bottoms = Counter(), Counter(), Counter(), Counter()
    for node in raw_nodes:
        if node.get("title_y") is not None:
            title_offsets[round(node["title_y"] - node["y"], 1)] += 1
        if node.get("sub_y") is not None and node.get("title_y") is not None:
            sub_offsets[round(node["sub_y"] - node["title_y"], 1)] += 1
        if node.get("meta_y") is not None:
            meta_bottoms[round(node["y"] + node["height"] - node["meta_y"], 1)] += 1
        if node.get("tag_y") is not None:
            tag_bottoms[round(node["y"] + node["height"] - node["tag_y"], 1)] += 1
    rhythm = {}
    if title_offsets:
        rhythm["title"] = title_offsets.most_common(1)[0][0]
    if sub_offsets:
        rhythm["sub"] = sub_offsets.most_common(1)[0][0]
    if meta_bottoms:
        rhythm["meta_bottom"] = meta_bottoms.most_common(1)[0][0]
    if tag_bottoms:
        rhythm["tag_bottom"] = tag_bottoms.most_common(1)[0][0]
    # Legacy layout evidence, not class names: the former band inset was 12px, the current one 16px,
    # and old files also use the retired `lane-band` / `nd-*` class vocabulary.
    legacy_source = bool(
        re.search(r'class="[^\"]*lane-band', svg, re.I)
        or re.search(r'class="[^\"]*\bnd-(?:title|sub|meta|tag)\b', svg, re.I)
        or any(lane["_x"] < 13.0 for lane in lanes))
    extraction_warnings = []
    if not raw_nodes and not edges and not lanes:
        extraction_warnings.append("no recognized diagram elements were found; extracted spec may be incomplete")
    recognized = bool(raw_nodes or edges or lanes or free_labels)
    spec = {"type": ("swimlane" if lanes else "process") if recognized else "unknown",
            "title": metadata.get("title", title),
            "subtitle": metadata.get("subtitle", "Extracted from existing SVG/HTML."),
            "number": metadata.get("number"), "figure_meta": metadata.get("figure_meta", ""),
            "_legacy_swimlane": legacy_source,
            "lanes": clean_lanes, "columns": ordered_columns, "edges": edges,
            "labels": free_labels,
            "_rhythm": rhythm, "_legacy_extracted": True,
            "_extraction_warnings": extraction_warnings,
            "_viewbox": [numbers[2], numbers[3]] if len(numbers) >= 4 else [1200, 800]}
    return spec


def is_empty_spec(spec: dict) -> bool:
    """True when extraction recognized no diagram elements at all."""
    nodes = sum(len(column.get("nodes", [])) for column in spec.get("columns", []))
    return not (nodes or spec.get("edges") or spec.get("lanes")
                or spec.get("messages") or spec.get("participants") or spec.get("labels"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a generic HTML/SVG diagram into JSON")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--svg-index", type=int, default=0)
    parser.add_argument("--fig", type=int, help="legacy figure number selector")
    parser.add_argument("--all", action="store_true", help="extract every SVG")
    parser.add_argument("-d", "--directory", type=Path, help="output directory used with --all")
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    svgs = re.findall(r"<svg\b.*?</svg>", text, re.S | re.I)
    if not svgs:
        raise SystemExit("no SVG element found")
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S) or re.search(r"<h2[^>]*>(.*?)</h2>", text, re.S)
    title = text_value(heading.group(1)) if heading else args.source.stem

    def metadata_for(section: str | None, fallback_title: str) -> dict:
        source = section or text
        heading_local = re.search(r"<h1[^>]*>(.*?)</h1>", source, re.S) or re.search(r"<h2[^>]*>(.*?)</h2>", source, re.S)
        number_local = re.search(r'<(?:span|div)\b[^>]*class="[^"]*(?:sw-num|num|figure-number)[^"]*"[^>]*>\s*0*([0-9]+)', source, re.I)
        meta_local = re.search(r'<p\b[^>]*class="[^"]*figure-meta[^"]*"[^>]*>(.*?)</p>', source, re.S | re.I)
        subtitle_local = re.search(r'<p\b[^>]*class="[^"]*sub[^"]*"[^>]*>(.*?)</p>', source, re.S | re.I)
        return {"title": text_value(heading_local.group(1)) if heading_local else fallback_title,
                "number": number_local.group(1) if number_local else None,
                "figure_meta": text_value(meta_local.group(1)).replace("泳道：", "").strip() if meta_local else "",
                "subtitle": text_value(subtitle_local.group(1)) if subtitle_local else "Extracted from existing SVG/HTML."}
    selected = [(index, svg, None) for index, svg in enumerate(svgs)]
    if args.fig is not None:
        selected = []
        sections = re.findall(r"<section\b.*?</section>", text, re.S | re.I)
        for index, section in enumerate(sections):
            hit = re.search(r'<(?:span|div)\b[^>]*class="[^"]*(?:num|figure-number)[^"]*"[^>]*>\s*0*([0-9]+)', section, re.I)
            if hit and int(hit.group(1)) == args.fig:
                svg = re.search(r"<svg\b.*?</svg>", section, re.S | re.I)
                if svg:
                    selected = [(index, svg.group(0), section)]
                break
        if not selected:
            raise SystemExit(f"figure {args.fig} not found")
    elif not args.all:
        if args.svg_index < 0 or args.svg_index >= len(svgs):
            raise SystemExit(f"svg index out of range: {args.svg_index} (found {len(svgs)})")
        selected = [(args.svg_index, svgs[args.svg_index], None)]
    if args.all:
        directory = args.directory or args.output or Path("extracted")
        directory.mkdir(parents=True, exist_ok=True)
        empty = False
        for index, svg, section in selected:
            spec = extract_svg(svg, f"{title} {index + 1}", metadata_for(section, f"{title} {index + 1}"))
            path = directory / f"{args.source.stem}-{index + 1}.json"
            path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"written: {path}")
            for warning in spec.get("_extraction_warnings", []):
                print(f"warning: {warning}")
            empty = empty or is_empty_spec(spec)
        return 2 if empty else 0
    spec = extract_svg(selected[0][1], title, metadata_for(selected[0][2], title))
    output = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"written: {args.output}")
        for warning in spec.get("_extraction_warnings", []):
            print(f"warning: {warning}")
    else:
        for warning in spec.get("_extraction_warnings", []):
            print(f"warning: {warning}", file=sys.stderr)
        print(output, end="")
    return 2 if is_empty_spec(spec) else 0


if __name__ == "__main__":
    raise SystemExit(main())
