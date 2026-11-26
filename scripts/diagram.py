#!/usr/bin/env python3
"""Render and validate domain-neutral diagram specs.

The input is semantic JSON. Coordinates are calculated here so a diagram can
be revised by changing nodes, lanes, columns, and edges instead of drawing
SVG by hand. The output is a self-contained HTML document with inline SVG.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from pathlib import Path

PALETTE = {
    "actor": ("#eff6ff", "#2563eb"), "process": ("#effcf8", "#0f766e"),
    "decision": ("#fffbeb", "#b45309"), "system": ("#f5f3ff", "#7c3aed"),
    "external": ("#faf5ff", "#9333ea"), "state": ("#ecfeff", "#0e7490"),
    "data": ("#f0fdf4", "#15803d"), "note": ("#f8fafc", "#64748b"),
    "yc": ("#eff6ff", "#2563eb"), "pf": ("#effcf8", "#0f766e"), "ext": ("#faf5ff", "#7c3aed"),
}
LANE_PALETTE = {"people": ("#fbfcff", "#c7d2fe"), "platform": ("#f7fdfb", "#b7e4d8"), "external": ("#faf8ff", "#ddd6fe"),
                "yc": ("#fbfcff", "#c7d2fe"), "pf": ("#f7fdfb", "#b7e4d8"), "ext": ("#faf8ff", "#ddd6fe")}
EDGE_STYLE = {
    "flow": ("#64748b", "", "arrow"), "request": ("#2563eb", "", "arrowBlue"),
    "response": ("#2563eb", "7 5", "arrowBlue"), "return": ("#64748b", "7 5", "arrow"),
    "dependency": ("#b45309", "7 5", "arrowAmber"), "external": ("#7c3aed", "7 5", "arrowPurple"),
}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def text_width(value: str, size: float, bold: bool = False) -> float:
    width = sum(1.0 if ord(ch) > 0x2E80 else 0.52 for ch in value)
    return width * size * (1.04 if bold else 1.0)


def wrap(value: object, size: float, max_width: float, bold: bool = False) -> list[str]:
    raw = str(value or "")
    if not raw:
        return []
    result: list[str] = []
    for part in raw.splitlines() or [""]:
        current = ""
        for char in part:
            if current and text_width(current + char, size, bold) > max_width:
                result.append(current)
                current = char
            else:
                current += char
        result.append(current)
    return result


def normalize(spec: dict) -> dict:
    """Accept both node-based specs and the compact columns form."""
    spec = dict(spec)
    legacy_columns = bool(not spec.get("nodes") and spec.get("columns"))
    if legacy_columns:
        nodes = []
        for column, group in enumerate(spec.get("columns", [])):
            for item in group.get("nodes", []):
                node = dict(item)
                node.setdefault("column", column)
                nodes.append(node)
        spec["nodes"] = nodes
    if "_legacy_swimlane" in spec:
        spec["_legacy_swimlane"] = bool(spec["_legacy_swimlane"])
    else:
        spec["_legacy_swimlane"] = bool(legacy_columns or spec.get("number") is not None or
                                         spec.get("figure_meta") is not None or spec.get("_viewbox") is not None)
    for node in spec.get("nodes", []):
        node["_legacy_compat"] = bool(spec.get("_legacy_swimlane"))
        if "width" not in node and "w" in node:
            node["width"] = node["w"]
        if "height" not in node and "h" in node:
            node["height"] = node["h"]
        if node.get("shape") == "decision" and "kind" not in node:
            node["kind"] = "decision"
        if node.get("cls") == "external" and "kind" not in node:
            node["kind"] = "external"
    spec.setdefault("type", "process")
    if spec.get("type") == "sequence" or spec.get("participants") or spec.get("messages"):
        spec["type"] = "sequence"
        spec.setdefault("participants", spec.pop("actors", []))
        spec.setdefault("messages", [])
        spec.setdefault("annotations", spec.pop("notes", []))
        return spec
    spec.setdefault("nodes", [])
    spec.setdefault("edges", [])
    spec.setdefault("lanes", [])
    if not spec["lanes"]:
        inferred = []
        for node in spec["nodes"]:
            lane = node.get("lane")
            if lane and lane not in {item["id"] for item in inferred}:
                inferred.append({"id": lane, "name": lane, "sub": ""})
        spec["lanes"] = inferred
    return spec


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("spec root must be an object")
    return normalize(data)


def node_height(node: dict, width: float) -> tuple[float, dict[str, list[str]]]:
    kind = node.get("kind", "process")
    fixed_geometry = "height" in node or "h" in node
    legacy = bool(node.get("_legacy_compat"))
    title_limit = 100000 if fixed_geometry else width - (16 if legacy else 24)
    sub_limit = 100000 if fixed_geometry else width - (12 if legacy else 24)
    footer_limit = 100000 if fixed_geometry else width - (8 if legacy else 20)
    title = wrap(node.get("title", node.get("id", "")), 15 if kind != "decision" else 13, title_limit, True)
    sub = wrap(node.get("sub", ""), 10.5, sub_limit)
    meta = wrap(node.get("meta", ""), 8, footer_limit, True)
    tag = wrap(node.get("tag", ""), 9, footer_limit, True)
    if "height" in node:
        return float(node["height"]), {"title": title, "sub": sub, "meta": meta, "tag": tag}
    if kind == "decision":
        h = max(94.0, 28 + 17 * len(title) + 14 * len(sub))
    else:
        h = max(78.0, 22 + 19 * max(1, len(title)) + 14 * len(sub) + 12 * len(meta) + 14 * len(tag))
    return h, {"title": title, "sub": sub, "meta": meta, "tag": tag}


def prepare(spec: dict) -> tuple[dict, list[str]]:
    if spec.get("type") == "sequence":
        return prepare_sequence(spec)
    errors: list[str] = []
    lanes = spec.get("lanes", [])
    lane_ids = [lane.get("id") for lane in lanes]
    if len(lane_ids) != len(set(lane_ids)):
        errors.append("lane ids must be unique")
    lane_index = {lane_id: i for i, lane_id in enumerate(lane_ids)}
    nodes = spec.get("nodes", [])
    ids = [node.get("id") for node in nodes]
    if any(not node_id for node_id in ids):
        errors.append("node id is required")
    if len(ids) != len(set(ids)):
        errors.append("node ids must be unique")
    by_id = {node.get("id"): node for node in nodes}
    for node in nodes:
        lane = node.get("lane")
        if lanes and lane and lane not in lane_index:
            errors.append(f"node {node.get('id')} references unknown lane {lane}")
    for edge in spec.get("edges", []):
        if edge.get("from") not in by_id or edge.get("to") not in by_id:
            errors.append(f"edge {edge.get('from')} -> {edge.get('to')} references unknown node")

    max_column = max((int(node.get("column", i)) for i, node in enumerate(nodes)), default=0)
    fixed = bool(nodes) and all("x" in node and "y" in node for node in nodes)
    legacy_auto = bool(spec.get("_legacy_swimlane") and not fixed)
    left, top, right, lane_top, lane_bottom = ((72.0, 12.0, 72.0, 50.0, 34.0) if legacy_auto else (94.0, 82.0, 70.0, 62.0, 40.0))
    col_gap, lane_gap, default_w = ((79.2, 16.0, 150.0) if legacy_auto else (58.0, 20.0, 190.0))
    node_gap = 20.0 if legacy_auto else 18.0
    prepared: dict[str, dict] = {}
    col_widths = [default_w for _ in range(max_column + 1)]
    for index, node in enumerate(nodes):
        col = max(0, int(node.get("column", index)))
        width = float(node.get("width", default_w))
        height, lines = node_height(node, width)
        if spec.get("_legacy_swimlane") and "height" not in node and "h" not in node:
            height = max(96.0, 16 + 22 + 19 * max(len(lines["title"]) - 1, 0) +
                         19 * len(lines["sub"]) + 13 * len(lines["meta"]) + 16)
        prepared[node["id"]] = dict(node, column=col, lane=node.get("lane"), width=width,
                                     height=height, lines=lines, kind=node.get("kind", "process"),
                                     fixed_geometry=fixed)
        while len(col_widths) <= col:
            col_widths.append(default_w)
        col_widths[col] = max(col_widths[col], width)
    if not legacy_auto:
        label_gap = max((text_width(str(edge.get("label", "")), 11) + 24 for edge in spec.get("edges", []) if edge.get("label")), default=0.0)
        col_gap = max(col_gap, label_gap)

    lane_specs = lanes or [{"id": "__default__", "name": "", "sub": ""}]
    lane_ids = [lane["id"] for lane in lane_specs]
    lane_index = {lane_id: i for i, lane_id in enumerate(lane_ids)}
    for node in prepared.values():
        if node["lane"] not in lane_index:
            node["lane"] = lane_ids[0]
    lane_heights: dict[str, float] = {}
    for lane_id in lane_ids:
        largest = 0.0
        for col in range(len(col_widths)):
            group = [n for n in prepared.values() if n["lane"] == lane_id and n["column"] == col]
            if group:
                largest = max(largest, sum(n["height"] for n in group) + node_gap * (len(group) - 1))
        configured = next(lane for lane in lane_specs if lane["id"] == lane_id)
        pad_top = float(configured.get("pad_top", lane_top))
        pad_bottom = float(configured.get("pad_bottom", lane_bottom))
        minimum_lane = 0.0 if legacy_auto else 154.0
        lane_heights[lane_id] = float(configured.get("_h_fixed", configured.get("height", 0))) or max(minimum_lane, pad_top + largest + pad_bottom)

    if legacy_auto:
        width = max(float(spec.get("_viewbox", [1440, 0])[0] or 1440), left + right + sum(col_widths) + col_gap * max(0, len(col_widths) - 1))
        col_gap = (width - left - right - sum(col_widths)) / max(1, len(col_widths) - 1)
        automatic_width = width
    else:
        automatic_width = max(1180.0, left + right + sum(col_widths) + col_gap * max(0, len(col_widths) - 1))
    width = float(spec.get("_viewbox", [automatic_width, 0])[0] or automatic_width) if fixed else automatic_width
    height = float(spec.get("_viewbox", [0, 0])[1] or (top + sum(lane_heights.values()) + lane_gap * max(0, len(lane_ids) - 1) + 34)) if fixed else top + sum(lane_heights.values()) + lane_gap * max(0, len(lane_ids) - 1) + 34
    lane_boxes: dict[str, tuple[float, float]] = {}
    cursor = top
    for lane_id in lane_ids:
        configured = next(lane for lane in lane_specs if lane["id"] == lane_id)
        lane_y = configured.get("y", configured.get("_y", cursor)) if fixed else cursor
        lane_boxes[lane_id] = (float(lane_y), lane_heights[lane_id])
        cursor += lane_heights[lane_id] + lane_gap
    col_x: list[float] = []
    cursor = left
    for col_width in col_widths:
        col_x.append(cursor)
        cursor += col_width + col_gap
    for lane_id in lane_ids:
        by, bh = lane_boxes[lane_id]
        configured = next(lane for lane in lane_specs if lane["id"] == lane_id)
        pad_top = float(configured.get("pad_top", lane_top))
        pad_bottom = float(configured.get("pad_bottom", lane_bottom))
        for col in range(len(col_widths)):
            group = [n for n in prepared.values() if n["lane"] == lane_id and n["column"] == col]
            if not group:
                continue
            total = sum(n["height"] for n in group) + node_gap * (len(group) - 1)
            y = by + pad_top + max(0.0, (bh - pad_top - pad_bottom - total) / 2)
            for node in sorted(group, key=lambda item: item["id"]):
                if not fixed:
                    node["x"], node["y"] = col_x[col], y
                y += node["height"] + node_gap
    layout = {"width": width, "height": height, "positions": prepared, "lanes": lane_specs,
              "lane_boxes": lane_boxes, "lane_index": lane_index, "col_x": col_x,
              "col_widths": col_widths, "top": top, "lane_gap": lane_gap,
              "fixed": fixed, "spec": spec}
    return layout, errors


def prepare_sequence(spec: dict) -> tuple[dict, list[str]]:
    """Lay out participants, lifelines, ordered messages, and annotations."""
    errors: list[str] = []
    participants = spec.get("participants", [])
    ids = [item.get("id") for item in participants]
    if any(not item_id for item_id in ids):
        errors.append("participant id is required")
    if len(ids) != len(set(ids)):
        errors.append("participant ids must be unique")
    by_id = {item.get("id"): item for item in participants}
    messages = spec.get("messages", [])
    for message in messages:
        if message.get("from") not in by_id or message.get("to") not in by_id:
            errors.append(f"message {message.get('from')} -> {message.get('to')} references unknown participant")

    fixed = bool(participants) and all("x" in item and "y" in item for item in participants)
    left, top, default_w, gap = 60.0, 18.0, 180.0, 42.0
    prepared: dict[str, dict] = {}
    for index, participant in enumerate(participants):
        width = float(participant.get("width", participant.get("w", default_w)))
        height = float(participant.get("height", participant.get("h", 46)))
        x = float(participant.get("x", left + index * (default_w + gap)))
        y = float(participant.get("y", top))
        prepared[participant["id"]] = dict(participant, x=x, y=y, width=width, height=height,
                                            title=participant.get("title", participant["id"]))
    if not fixed:
        available_width = float(spec.get("_viewbox", [0, 0])[0] or 0)
        if available_width and len(participants) > 1:
            gap = max(28.0, (available_width - 2 * left - len(participants) * default_w) / (len(participants) - 1))
        for index, participant in enumerate(participants):
            prepared[participant["id"]]["x"] = left + index * (default_w + gap)

    participant_bottom = max((item["y"] + item["height"] for item in prepared.values()), default=top + 46)
    row_h = float(spec.get("row_height", 54))
    lifeline_top = float(spec.get("lifeline_top", participant_bottom + 18))
    max_message_y = max((float(message.get("y", lifeline_top + 24 + index * row_h)) for index, message in enumerate(messages)), default=lifeline_top + 24)
    lifeline_bottom = float(spec.get("lifeline_bottom", max_message_y + 26))
    prepared_messages = []
    for index, message in enumerate(messages):
        source = prepared.get(message.get("from"))
        target = prepared.get(message.get("to"))
        y = float(message.get("y", lifeline_top + 24 + index * row_h))
        x1 = float(message.get("x1", source["x"] + source["width"] / 2 if source else 0))
        x2 = float(message.get("x2", target["x"] + target["width"] / 2 if target else 0))
        prepared_messages.append(dict(message, index=index, y=y, x1=x1, x2=x2,
                                      label=message.get("label", "")))
        lifeline_bottom = max(lifeline_bottom, y + 26)

    annotations = []
    for index, annotation in enumerate(spec.get("annotations", [])):
        item = dict(annotation)
        after = item.get("after", index + 1)
        if "y" not in item:
            try:
                after_index = int(after) - 1 if int(after) > 0 else int(after)
            except (TypeError, ValueError):
                after_index = index
            base_y = prepared_messages[min(max(after_index, 0), max(len(prepared_messages) - 1, 0))]["y"] if prepared_messages else lifeline_top
            item["y"] = base_y + 12
        item.setdefault("x", left)
        item.setdefault("width", max(180.0, min(520.0, text_width(str(item.get("text", "")), 12) + 28)))
        item.setdefault("height", 28.0)
        annotations.append(item)

    width = float(spec.get("_viewbox", [0, 0])[0] or (max((item["x"] + item["width"] for item in prepared.values()), default=left) + left))
    height = float(spec.get("_viewbox", [0, 0])[1] or (lifeline_bottom + 34))
    layout = {"mode": "sequence", "width": width, "height": height, "participants": prepared,
              "messages": prepared_messages, "annotations": annotations, "lifeline_top": lifeline_top,
              "lifeline_bottom": lifeline_bottom, "fixed": fixed, "spec": spec}
    return layout, errors


def center(box: dict) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def anchor(box: dict, target: tuple[float, float]) -> tuple[float, float]:
    cx, cy = center(box)
    tx, ty = target
    if abs(tx - cx) >= abs(ty - cy):
        return (box["x"] + box["width"], cy) if tx >= cx else (box["x"], cy)
    return (cx, box["y"] + box["height"]) if ty >= cy else (cx, box["y"])


def simplify_route(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        point = (float(point[0]), float(point[1]))
        if result and point == result[-1]:
            continue
        if len(result) >= 2:
            a, b = result[-2], result[-1]
            if (abs(a[0] - b[0]) < 0.5 and abs(b[0] - point[0]) < 0.5) or (abs(a[1] - b[1]) < 0.5 and abs(b[1] - point[1]) < 0.5):
                result[-1] = point
                continue
        result.append(point)
    return result


def has_short_approach_dogleg(points: list[tuple[float, float]], *, max_offset: float = 20) -> bool:
    """Detect a small sideways jog between parallel legs just before the arrow."""
    if len(points) < 4:
        return False
    start, bend, turn, tip = points[-4:]
    if math.dist(bend, turn) > max_offset or math.dist(turn, tip) > 30:
        return False
    for axis in (0, 1):
        sideways = 1 - axis
        if (abs(start[sideways] - bend[sideways]) < 0.5
                and abs(bend[axis] - turn[axis]) < 0.5
                and abs(bend[sideways] - turn[sideways]) >= 0.5
                and abs(turn[sideways] - tip[sideways]) < 0.5
                and (bend[axis] - start[axis]) * (tip[axis] - turn[axis]) > 0):
            return True
    return False


def segment_rect_distance(p: tuple[float, float], q: tuple[float, float], box: tuple[float, float, float, float]) -> float:
    """Distance for the axis-aligned segments emitted by the renderer."""
    x0, y0, x1, y1 = box
    ax, ay = p
    bx, by = q
    if abs(ay - by) < 0.5:
        left, right = min(ax, bx), max(ax, bx)
        dx = 0.0 if right >= x0 and left <= x1 else min(abs(left - x1), abs(x0 - right))
        dy = 0.0 if y0 <= ay <= y1 else min(abs(ay - y0), abs(ay - y1))
        return math.hypot(dx, dy)
    if abs(ax - bx) < 0.5:
        top, bottom = min(ay, by), max(ay, by)
        dy = 0.0 if bottom >= y0 and top <= y1 else min(abs(top - y1), abs(y0 - bottom))
        dx = 0.0 if x0 <= ax <= x1 else min(abs(ax - x0), abs(ax - x1))
        return math.hypot(dx, dy)
    return float("inf")


def expanded_box(node: dict, margin: float = 0.0) -> tuple[float, float, float, float]:
    return (node["x"] - margin, node["y"] - margin,
            node["x"] + node["width"] + margin, node["y"] + node["height"] + margin)


def route_score(layout: dict, edge: dict, points: list[tuple[float, float]]) -> tuple[float, int]:
    positions = layout["positions"]
    score = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(points, points[1:])) + max(0, len(points) - 2) * 7
    target = positions[edge["to"]]
    if len(points) >= 2:
        p, q = points[-2], points[-1]
        along_top_bottom = abs(p[1] - q[1]) < 0.5 and (abs(q[1] - target["y"]) < 1.5 or abs(q[1] - target["y"] - target["height"]) < 1.5)
        along_left_right = abs(p[0] - q[0]) < 0.5 and (abs(q[0] - target["x"]) < 1.5 or abs(q[0] - target["x"] - target["width"]) < 1.5)
        if along_top_bottom or along_left_right:
            score += 50000
    collisions = 0
    for node_id, node in positions.items():
        if node_id in {edge.get("from"), edge.get("to")}:
            continue
        near = expanded_box(node, 10)
        for p, q in zip(points, points[1:]):
            distance = segment_rect_distance(p, q, near)
            if distance < 0.5:
                collisions += 1
                score += 100000
                break
            if distance < 12:
                score += (12 - distance) * 45
    return score, collisions


def auto_route(layout: dict, edge: dict) -> list[tuple[float, float]]:
    a, b = layout["positions"][edge["from"]], layout["positions"][edge["to"]]
    start, end = anchor(a, center(b)), anchor(b, center(a))
    if abs(start[1] - end[1]) < 0.5 or abs(start[0] - end[0]) < 0.5:
        return [start, end]
    positions = layout["positions"]
    width, height = layout["width"], layout["height"]
    x_channels = {(start[0] + end[0]) / 2, start[0], end[0], start[0] - 18, start[0] + 18, end[0] - 18, end[0] + 18}
    y_channels = {(start[1] + end[1]) / 2, start[1], end[1], start[1] - 18, start[1] + 18, end[1] - 18, end[1] + 18}
    for node in positions.values():
        x_channels.update((node["x"] - 18, node["x"] + node["width"] + 18))
        y_channels.update((node["y"] - 18, node["y"] + node["height"] + 18))
    candidates: list[list[tuple[float, float]]] = []
    # A channel outside the node columns is safer than a diagonal or a route through a box.
    for channel in sorted(x_channels):
        if 12 <= channel <= width - 12:
            candidates.append(simplify_route([start, (channel, start[1]), (channel, end[1]), end]))
    for channel in sorted(y_channels):
        if 12 <= channel <= height - 12:
            candidates.append(simplify_route([start, (start[0], channel), (end[0], channel), end]))
    # Keep the old midpoint route as a fallback candidate.
    mid_x = (start[0] + end[0]) / 2
    candidates.append(simplify_route([start, (mid_x, start[1]), (mid_x, end[1]), end]))
    mid_y = (start[1] + end[1]) / 2
    candidates.append(simplify_route([start, (start[0], mid_y), (end[0], mid_y), end]))
    return min(candidates, key=lambda candidate: route_score(layout, edge, candidate))


def route(layout: dict, edge: dict) -> list[tuple[float, float]]:
    if edge.get("route"):
        return [tuple(map(float, point)) for point in edge["route"]]
    if not layout.get("fixed") and not layout["spec"].get("_legacy_swimlane"):
        return auto_route(layout, edge)
    a, b = layout["positions"][edge["from"]], layout["positions"][edge["to"]]
    ac, bc = center(a), center(b)
    if b["x"] > a["x"] + a["width"] + 2:
        start, end = anchor(a, bc), anchor(b, ac)
        if abs(start[1] - end[1]) < 0.5:
            return [start, end]
        mid = (start[0] + end[0]) / 2
        return [start, (mid, start[1]), (mid, end[1]), end]
    if b["x"] < a["x"] - 2:
        start, end = anchor(a, bc), anchor(b, ac)
        gap_left, gap_right = b["x"] + b["width"], a["x"]
        channel = (gap_left + gap_right) / 2 if gap_left < gap_right else max(a["x"] + a["width"], b["x"] + b["width"]) + 34
        return [start, (channel, start[1]), (channel, end[1]), end]
    if b["y"] >= a["y"] + a["height"]:
        start, end = anchor(a, bc), anchor(b, ac)
        mid = (start[1] + end[1]) / 2
        return [start, (start[0], mid), (end[0], mid), end]
    start, end = anchor(a, bc), anchor(b, ac)
    channel = min(a["y"], b["y"]) - 24
    return [start, (start[0], channel), (end[0], channel), end]

def segment_hits_box(p: tuple[float, float], q: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = box
    ax, ay = p
    bx, by = q
    if abs(ay - by) < 0.5:
        return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0
    if abs(ax - bx) < 0.5:
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    return False


def on_border(box: dict, point: tuple[float, float]) -> bool:
    x, y = point
    if box["kind"] == "decision":
        cx, cy = center(box)
        return abs(abs(x - cx) / (box["width"] / 2) + abs(y - cy) / (box["height"] / 2) - 1) < 0.14
    return (abs(x - box["x"]) < 1.0 and box["y"] - 1 <= y <= box["y"] + box["height"] + 1 or
            abs(x - box["x"] - box["width"]) < 1.0 and box["y"] - 1 <= y <= box["y"] + box["height"] + 1 or
            abs(y - box["y"]) < 1.0 and box["x"] - 1 <= x <= box["x"] + box["width"] + 1 or
            abs(y - box["y"] - box["height"]) < 1.0 and box["x"] - 1 <= x <= box["x"] + box["width"] + 1)


def sequence_check(layout: dict) -> list[str]:
    """Validate a sequence layout without treating historical SVG quirks as meaning."""
    issues: list[str] = []
    legacy = bool(layout.get("spec", {}).get("_legacy_extracted"))
    participants = list(layout.get("participants", {}).values())
    by_id = layout.get("participants", {})
    width, height = layout["width"], layout["height"]
    for i, left in enumerate(participants):
        for right in participants[i + 1:]:
            if (left["x"] < right["x"] + right["width"] - 1 and right["x"] < left["x"] + left["width"] - 1 and
                    left["y"] < right["y"] + right["height"] - 1 and right["y"] < left["y"] + left["height"] - 1):
                issues.append(f"participant-overlap: {left['id']} / {right['id']}")
    if layout["lifeline_top"] < 0 or layout["lifeline_bottom"] > height:
        if not legacy:
            issues.append("lifeline-out-of-viewbox")
    previous_y = None
    for message in layout.get("messages", []):
        y, x1, x2 = message["y"], message["x1"], message["x2"]
        if previous_y is not None and y <= previous_y:
            issues.append(f"message-order: row {message['index'] + 1} is not below the previous row")
        previous_y = y
        if message.get("from") not in by_id or message.get("to") not in by_id:
            continue
        if abs(x1 - x2) < 0.5:
            issues.append(f"message-zero-length: row {message['index'] + 1}")
        if not (0 <= x1 <= width and 0 <= x2 <= width and 0 <= y <= height):
            issues.append(f"message-out-of-viewbox: row {message['index'] + 1}")
        def endpoint_ok(value: float, participant: dict) -> bool:
            center = participant["x"] + participant["width"] / 2
            edges = (participant["x"], participant["x"] + participant["width"])
            return min(abs(value - center), *(abs(value - edge) for edge in edges)) <= 6.0
        if not endpoint_ok(x1, by_id[message["from"]]) or not endpoint_ok(x2, by_id[message["to"]]):
            issues.append(f"message-endpoint-misaligned: row {message['index'] + 1}")
        if y < layout["lifeline_top"] or y > layout["lifeline_bottom"]:
            if not legacy:
                issues.append(f"message-outside-lifelines: row {message['index'] + 1}")
        if message.get("label"):
            lx, ly = message.get("label_at", ((x1 + x2) / 2, y - 7))
            if not (0 <= float(lx) <= width and 0 <= float(ly) <= height):
                issues.append(f"label-out-of-viewbox: row {message['index'] + 1}")
    for index, annotation in enumerate(layout.get("annotations", []), 1):
        x, y = float(annotation.get("x", 0)), float(annotation.get("y", 0))
        w, h = float(annotation.get("width", 0)), float(annotation.get("height", 0))
        if x < 0 or y < 0 or x + w > width or y + h > height:
            issues.append(f"annotation-out-of-viewbox: {index}")
        if text_width(str(annotation.get("text", "")), 11, True) > max(0, w - 20):
            issues.append(f"annotation-text-overflow: {index}")
        for participant in participants:
            if (x < participant["x"] + participant["width"] and participant["x"] < x + w and
                    y < participant["y"] + participant["height"] and participant["y"] < y + h):
                issues.append(f"annotation-overlap: {index} / {participant['id']}")
    return sorted(set(issues))


def best_route_segment(points: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    return max(zip(points, points[1:]), key=lambda pair: abs(pair[0][0] - pair[1][0]) + abs(pair[0][1] - pair[1][1]))


def edge_label_position(layout: dict, edge: dict, points: list[tuple[float, float]]) -> tuple[float, float]:
    (x0, y0), (x1, y1) = best_route_segment(points)
    if edge.get("label_at"):
        return float(edge["label_at"][0]), float(edge["label_at"][1])
    if abs(y0 - y1) < 0.5:
        base = ((x0 + x1) / 2, y0 - 9)
    else:
        base = ((x0 + x1) / 2 + 10, (y0 + y1) / 2)
    # Pick a nearby position that does not sit on a node. This is deliberately
    # deterministic so the checker and renderer make the same choice.
    text = str(edge.get("label", ""))
    candidates = [base]
    if abs(y0 - y1) < 0.5:
        direction = 1 if x1 >= x0 else -1
        candidates.extend((base[0] + direction * dx, base[1] + dy) for dx in (8, -8, 16, -16) for dy in (0, -14, 14, -28, 28, -42, 42))
    else:
        candidates.extend((base[0] + dx, base[1] + dy) for dx in (0, -14, 14, -28, 28) for dy in (-10, 10, -22, 22))
    best = None
    for candidate in candidates:
        rect = label_box(text, candidate[0], candidate[1])
        overlap = 0
        for node in layout.get("positions", {}).values():
            overlap += int(boxes_overlap(rect, (node["x"], node["y"], node["x"] + node["width"], node["y"] + node["height"]), 1))
        boundary = 0
        for lane in layout.get("lanes", []):
            lane_y, lane_h = layout["lane_boxes"][lane["id"]]
            boundary += int(abs(rect[1] - lane_y) < 4 or abs(rect[3] - lane_y) < 4 or abs(rect[1] - (lane_y + lane_h)) < 4 or abs(rect[3] - (lane_y + lane_h)) < 4)
        out = int(rect[0] < 0 or rect[1] < 0 or rect[2] > layout["width"] or rect[3] > layout["height"])
        score = overlap * 10000 + boundary * 3000 + out * 100000 + abs(candidate[0] - base[0]) + abs(candidate[1] - base[1]) * 0.35
        if best is None or score < best[0]:
            best = (score, candidate)
    return best[1] if best else base


def label_box(text: str, x: float, y: float) -> tuple[float, float, float, float]:
    width = max(12.0, text_width(text, 11) + 4)
    return x - width / 2, y - 12, x + width / 2, y + 3


def boxes_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float], margin: float = 0.0) -> bool:
    return left[0] < right[2] + margin and right[0] < left[2] + margin and left[1] < right[3] + margin and right[1] < left[3] + margin


def check(layout: dict) -> list[str]:
    if layout.get("mode") == "sequence":
        return sequence_check(layout)
    spec, positions = layout["spec"], layout["positions"]
    issues: list[str] = []
    quality_warnings: list[str] = []
    legacy = bool(spec.get("_legacy_extracted") or spec.get("_legacy_swimlane"))

    def report(message: str, visual: bool = False) -> None:
        if visual and legacy:
            quality_warnings.append(message)
        else:
            issues.append(message)

    ids = list(positions)
    for i, left_id in enumerate(ids):
        left = positions[left_id]
        for right_id in ids[i + 1:]:
            right = positions[right_id]
            if (left["x"] < right["x"] + right["width"] - 1 and right["x"] < left["x"] + left["width"] - 1 and
                    left["y"] < right["y"] + right["height"] - 1 and right["y"] < left["y"] + left["height"] - 1):
                issues.append(f"node-overlap: {left_id} / {right_id}")
    for node_id, node in positions.items():
        by, bh = layout["lane_boxes"][node["lane"]]
        if node["y"] < by or node["y"] + node["height"] > by + bh:
            issues.append(f"lane-overflow: {node_id}")
        fixed_geometry = bool(node.get("fixed_geometry"))
        for field, size, bold, limit in (("title", 15, True, 3), ("sub", 10.5, False, 3), ("meta", 8, True, 2), ("tag", 9, True, 2)):
            lines = node["lines"][field]
            if not fixed_geometry and len(lines) > limit:
                issues.append(f"text-too-dense: {node_id}.{field} has {len(lines)} lines")
            for line in lines:
                inner = node["width"] - (8 if node.get("_legacy_compat") and field in {"meta", "tag"} else 12 if node.get("_legacy_compat") and field == "sub" else 16 if node.get("_legacy_compat") and field == "title" else 18)
                if not fixed_geometry and text_width(line, size, bold) > inner:
                    issues.append(f"text-overflow: {node_id}.{field}")
    for edge in spec.get("edges", []):
        if edge.get("from") not in positions or edge.get("to") not in positions:
            continue
        points = route(layout, edge)
        source, target = positions[edge["from"]], positions[edge["to"]]
        if len(points) < 2 or not on_border(source, points[0]):
            report(f"arrow-off-border: {edge.get('from')} start")
        if len(points) < 2 or not on_border(target, points[-1]):
            report(f"arrow-off-border: {edge.get('to')} end")
        if len(points) >= 2:
            p, q = points[-2], points[-1]
            approach = math.hypot(q[0] - p[0], q[1] - p[1])
            if approach < 12:
                report(f"arrow-short-approach: {edge['from']} -> {edge['to']}", visual=True)
            if has_short_approach_dogleg(points):
                report(f"arrow-short-dogleg: {edge['from']} -> {edge['to']}", visual=True)
            # An arrow that travels along the target border reads as if it is pressing into the box.
            if ((abs(p[1] - q[1]) < 0.5 and (abs(q[1] - target["y"]) < 1.5 or abs(q[1] - target["y"] - target["height"]) < 1.5)) or
                    (abs(p[0] - q[0]) < 0.5 and (abs(q[0] - target["x"]) < 1.5 or abs(q[0] - target["x"] - target["width"]) < 1.5))):
                report(f"arrow-runs-along-target-border: {edge['from']} -> {edge['to']}", visual=True)
        for node_id, node in positions.items():
            if node_id in (edge["from"], edge["to"]):
                continue
            box = (node["x"] + 2, node["y"] + 2, node["x"] + node["width"] - 2, node["y"] + node["height"] - 2)
            if any(segment_hits_box(points[i], points[i + 1], box) for i in range(len(points) - 1)):
                report(f"edge-cross: {edge['from']} -> {edge['to']} crosses {node_id}")
            clearance = min((segment_rect_distance(points[i], points[i + 1], expanded_box(node, 0)) for i in range(len(points) - 1)), default=float("inf"))
            if clearance < 10:
                report(f"edge-too-close: {edge['from']} -> {edge['to']} near {node_id}", visual=True)
        if edge.get("label"):
            lx, ly = edge_label_position(layout, edge, points)
            label_rect = label_box(str(edge["label"]), lx, ly)
            for node_id, node in positions.items():
                if boxes_overlap(label_rect, (node["x"], node["y"], node["x"] + node["width"], node["y"] + node["height"]), 1):
                    report(f"label-overlap: {edge.get('label')} / {node_id}", visual=True)
            for lane in layout["lanes"]:
                lane_y, lane_h = layout["lane_boxes"][lane["id"]]
                lane_left, lane_right = 12.0, layout["width"] - 12.0
                if label_rect[2] >= lane_left and label_rect[0] <= lane_right and (abs(label_rect[3] - lane_y) < 3 or abs(label_rect[1] - (lane_y + lane_h)) < 3):
                    report(f"label-lane-boundary: {edge.get('label')} / {lane['id']}", visual=True)
    for label in spec.get("labels", []):
        text = str(label.get("text", ""))
        if not text:
            continue
        rect = label_box(text, float(label.get("x", 0)), float(label.get("y", 0)))
        for node_id, node in positions.items():
            if boxes_overlap(rect, (node["x"], node["y"], node["x"] + node["width"], node["y"] + node["height"]), 1):
                report(f"label-overlap: {text} / {node_id}", visual=True)
        for lane in layout["lanes"]:
            lane_y, lane_h = layout["lane_boxes"][lane["id"]]
            if abs(rect[3] - lane_y) < 3 or abs(rect[1] - (lane_y + lane_h)) < 3:
                report(f"label-lane-boundary: {text} / {lane['id']}", visual=True)
    for node in positions.values():
        if node["kind"] == "decision" and not (spec.get("_legacy_extracted") or spec.get("_legacy_swimlane")):
            outgoing = [edge for edge in spec.get("edges", []) if edge.get("from") == node["id"]]
            if not outgoing:
                issues.append(f"decision-without-path: {node['id']}")
            elif any(not edge.get("label") for edge in outgoing):
                issues.append(f"decision-outcome-unlabeled: {node['id']}")
    layout["quality_warnings"] = sorted(set(quality_warnings))
    return sorted(set(issues))

def sequence_svg(layout: dict) -> str:
    spec = layout["spec"]
    width, height = layout["width"], layout["height"]
    participants = layout["participants"]
    colors = {"actor": ("#eff6ff", "#2563eb"), "pf": ("#ecfdf5", "#0f766e"),
              "ext": ("#faf5ff", "#7c3aed"), "hm": ("#fff7ed", "#c2410c")}
    out = [f'<svg viewBox="0 0 {width:.1f} {height:.1f}" role="img" data-generation="diagram-production" aria-label="{esc(spec.get("title", "Sequence diagram"))}">']
    out.append('<defs><marker id="seq-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#475569"/></marker><marker id="seq-arrow-return" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#64748b"/></marker><marker id="seq-arrow-alert" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#9a3412"/></marker></defs>')
    for participant in participants.values():
        x, y, w, h = participant["x"], participant["y"], participant["width"], participant["height"]
        visual = participant.get("cls") or participant.get("class") or "actor"
        fill, stroke = colors.get(visual, colors["actor"])
        fill, stroke = participant.get("fill", fill), participant.get("stroke", stroke)
        out.append(f'<rect class="actor {esc(visual)}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{float(participant.get("rx", 11)):.1f}" fill="{esc(fill)}" stroke="{esc(stroke)}" stroke-width="1.8"/>')
        out.append(f'<text class="actor-t" x="{x + w / 2:.1f}" y="{y + h / 2 + 5:.1f}" text-anchor="middle">{esc(participant.get("title", participant["id"]))}</text>')
    for participant in participants.values():
        cx = participant["x"] + participant["width"] / 2
        out.append(f'<line class="lifeline" x1="{cx:.1f}" y1="{layout["lifeline_top"]:.1f}" x2="{cx:.1f}" y2="{layout["lifeline_bottom"]:.1f}" stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="5 5"/>')
    for message in layout.get("messages", []):
        x1, x2, y = message["x1"], message["x2"], message["y"]
        kind = message.get("kind", "flow")
        response = kind in {"response", "return"} or message.get("ret")
        alert = message.get("alert") or message.get("color") == "#9a3412"
        color = message.get("color") or ("#9a3412" if alert else "#64748b" if response else "#475569")
        marker = "seq-arrow-alert" if alert else "seq-arrow-return" if response else "seq-arrow"
        dash = ' stroke-dasharray="7 5"' if response else ""
        out.append(f'<line class="msg{" ret" if response else ""}" x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{esc(color)}" stroke-width="1.8"{dash} marker-end="url(#{marker})"/>')
        # Keep the arrowhead in the DOM as a semantic artifact, while relying on the marker for robust rendering.
        if message.get("legacy_polygon"):
            points = message["legacy_polygon"]
            out.append(f'<polygon class="msg-arrow" points="{esc(points)}" fill="{esc(color)}"/>')
        if message.get("label"):
            lx, ly = message.get("label_at", ((x1 + x2) / 2, y - 7))
            out.append(f'<text class="lbl" x="{float(lx):.1f}" y="{float(ly):.1f}" fill="{esc(color)}">{esc(message["label"])}</text>')
    for annotation in layout.get("annotations", []):
        x, y, w, h = float(annotation.get("x", 0)), float(annotation.get("y", 0)), float(annotation.get("width", 180)), float(annotation.get("height", 28))
        fill, stroke = annotation.get("fill", "#fff7ed"), annotation.get("stroke", "#fed7aa")
        out.append(f'<rect class="tag" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="7" fill="{esc(fill)}" stroke="{esc(stroke)}" stroke-width="1.2"/>')
        out.append(f'<text class="tag-t" x="{x + 10:.1f}" y="{y + h - 7:.1f}">{esc(annotation.get("text", ""))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg(layout: dict) -> str:
    if layout.get("mode") == "sequence":
        return sequence_svg(layout)
    spec, positions = layout["spec"], layout["positions"]
    width, height = layout["width"], layout["height"]
    out = [f'<svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" data-generation="diagram-production" aria-label="{esc(spec.get("title", "Diagram"))}">']
    out.append('<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#64748b"/></marker><marker id="arrowBlue" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#2563eb"/></marker><marker id="arrowAmber" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#b45309"/></marker><marker id="arrowPurple" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#7c3aed"/></marker></defs>')
    for lane in layout["lanes"]:
        y, lane_h = layout["lane_boxes"][lane["id"]]
        lane_style = lane.get("style") or lane.get("id")
        lane_custom = (spec.get("palette") or {}).get(lane_style, {})
        fill, stroke = LANE_PALETTE.get(lane_style, ("#f8fafc", "#dfe6ef"))
        fill = lane.get("fill", lane_custom.get("band_fill", fill))
        stroke = lane.get("stroke", lane_custom.get("band_stroke", stroke))
        band_x, band_width, title_x = (12.0, width - 24.0, 30.0) if spec.get("_legacy_swimlane") else (16.0, width - 32.0, 34.0)
        out.append(f'<rect class="lane {esc(lane_style)}" x="{band_x:.1f}" y="{y:.1f}" width="{band_width:.1f}" height="{lane_h:.1f}" rx="12" fill="{esc(fill)}" stroke="{esc(stroke)}" stroke-width="1.4"/>')
        if lane.get("name"):
            out.append(f'<text class="lane-title" x="{title_x:.1f}" y="{y + 28:.1f}">{esc(lane["name"])}</text>')
        if lane.get("sub"):
            out.append(f'<text class="lane-sub" x="{title_x:.1f}" y="{y + 48:.1f}">{esc(lane["sub"])}</text>')
        if lane.get("stage"):
            out.append(f'<text class="lane-sub" x="34" y="{y + lane_h - 12:.1f}">{esc(lane["stage"])}</text>')
    for edge in spec.get("edges", []):
        if edge.get("from") not in positions or edge.get("to") not in positions:
            continue
        points = route(layout, edge)
        edge_kind = edge.get("kind", "flow")
        if edge.get("ext") or positions[edge["from"]].get("lane") == "ext" or positions[edge["to"]].get("lane") == "ext":
            edge_kind = "external"
        elif edge.get("dash"):
            edge_kind = "return"
        color, dash, marker = EDGE_STYLE.get(edge_kind, EDGE_STYLE["flow"])
        path = f'M {points[0][0]:.1f} {points[0][1]:.1f}'
        for p, q in zip(points, points[1:]):
            path += f' H {q[0]:.1f}' if abs(p[1] - q[1]) < 0.5 else f' V {q[1]:.1f}'
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        color = edge.get("color", color)
        out.append(f'<path class="edge" d="{path}" fill="none" stroke="{esc(color)}" stroke-width="2.2"{dash_attr} marker-end="url(#{marker})"/>')
        if edge.get("label"):
            lx, ly = edge_label_position(layout, edge, points)
            out.append(f'<text class="edge-label" x="{float(lx):.1f}" y="{float(ly):.1f}" text-anchor="middle" fill="{esc(color)}">{esc(edge["label"])}</text>')
    rhythm = spec.get("_rhythm") or {}
    title_step = float(rhythm.get("title", 24 if spec.get("_legacy_swimlane") else 18))
    sub_step = float(rhythm.get("sub", 19 if spec.get("_legacy_swimlane") else 21))
    tag_bottom = float(rhythm.get("tag_bottom", 6))
    meta_bottom = float(rhythm.get("meta_bottom", 21))
    for node in positions.values():
        x, y, w, h, kind = node["x"], node["y"], node["width"], node["height"], node["kind"]
        legacy_lane_visual = node.get("lane") if spec.get("_legacy_swimlane") and node.get("lane") in {"yc", "pf", "ext"} else None
        visual = node.get("cls") or legacy_lane_visual or ("external" if node.get("lane") == "ext" else kind)
        if kind == "decision":
            fill, stroke = PALETTE["decision"]
        elif visual == "bpm":
            fill, stroke = "#fff7ed", "#ea580c"
        else:
            fill, stroke = PALETTE.get(visual, PALETTE.get(kind, PALETTE["process"]))
        custom = (spec.get("palette") or {}).get(visual, {})
        fill, stroke = custom.get("fill", node.get("fill", fill)), custom.get("stroke", node.get("stroke", stroke))
        if kind == "decision":
            points = f'{x + w / 2:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w / 2:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}'
            out.append(f'<polygon class="node decision" points="{points}" fill="{esc(node.get("fill", fill))}" stroke="{esc(node.get("stroke", stroke))}" stroke-width="2"/>')
        else:
            radius = 16 if kind == "state" else 9
            dash = ' stroke-dasharray="7 5"' if visual in {"external", "ext"} or custom.get("dash") else ''
            if custom.get("dash"):
                dash = f' stroke-dasharray="{esc(custom["dash"])}"'
            out.append(f'<rect class="node {esc(visual)}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius}" fill="{esc(fill)}" stroke="{esc(stroke)}" stroke-width="2"{dash}/>')
        cx = x + w / 2
        title_lines = node["lines"]["title"][:3]
        if kind == "decision" and spec.get("_legacy_swimlane"):
            title_y = float(node.get("title_y", y + h / 2 - 4))
            title_step_local = 15.0
        elif spec.get("_legacy_swimlane"):
            title_y = y + title_step
            title_step_local = title_step
        else:
            title_y = y + 24
            title_step_local = title_step
        for i, line in enumerate(title_lines):
            cls = "decision-title" if kind == "decision" else "node-title"
            text_color = custom.get("text", "#92400e" if kind == "decision" else "#172033")
            out.append(f'<text class="{cls}" x="{cx:.1f}" y="{title_y + i * title_step_local:.1f}" text-anchor="middle" fill="{esc(text_color)}">{esc(line)}</text>')
        if node["lines"]["sub"]:
            if kind == "decision" and spec.get("_legacy_swimlane"):
                sub_y = float(node.get("sub_y", y + h / 2 + 15))
                sub_step_local = 11.0
            elif spec.get("_legacy_swimlane"):
                sub_y = y + title_step + title_step * (max(len(title_lines), 1) - 1) + sub_step
                sub_step_local = 13.0
            else:
                sub_y = title_y + sub_step * max(len(title_lines), 1)
                sub_step_local = 13.0
            for i, line in enumerate(node["lines"]["sub"][:2]):
                sub_cls = "decision-sub" if kind == "decision" else "node-sub"
                out.append(f'<text class="{sub_cls}" x="{cx:.1f}" y="{sub_y + i * sub_step_local:.1f}" text-anchor="middle">{esc(line)}</text>')
        if spec.get("_legacy_swimlane"):
            meta_y = float(node.get("meta_y", y + h - meta_bottom))
            tag_y = float(node.get("tag_y", y + h - tag_bottom))
            for i, line in enumerate(node["lines"]["meta"]):
                meta_cls = node.get("meta_cls") or visual
                meta_color = (spec.get("palette") or {}).get(meta_cls, {}).get("text", custom.get("text", "#64748b"))
                out.append(f'<text class="node-footer {esc(meta_cls)}" x="{cx:.1f}" y="{meta_y - (len(node["lines"]["meta"]) - i - 1) * 10:.1f}" text-anchor="middle" fill="{esc(meta_color)}">{esc(line)}</text>')
            for i, line in enumerate(node["lines"]["tag"]):
                tag_cls = node.get("tag_cls") or visual
                tag_color = (spec.get("palette") or {}).get(tag_cls, {}).get("text", custom.get("text", "#64748b"))
                out.append(f'<text class="node-footer {esc(tag_cls)}" x="{cx:.1f}" y="{tag_y - (len(node["lines"]["tag"]) - i - 1) * 11:.1f}" text-anchor="middle" fill="{esc(tag_color)}">{esc(line)}</text>')
        else:
            footer = node["lines"]["meta"] + node["lines"]["tag"]
            for i, line in enumerate(footer):
                footer_color = custom.get("text", "#64748b")
                out.append(f'<text class="node-footer" x="{cx:.1f}" y="{y + h - 12 - (len(footer) - i - 1) * 11:.1f}" text-anchor="middle" fill="{esc(footer_color)}">{esc(line)}</text>')
    for label in spec.get("labels", []):
        label_class = "edge-label" + (" external" if label.get("ext") else "")
        out.append(f'<text class="{label_class}" x="{float(label.get("x", 0)):.1f}" y="{float(label.get("y", 0)):.1f}">{esc(label.get("text", ""))}</text>')
    out.append("</svg>")
    return "".join(out)


def render(layout: dict) -> str:
    spec = layout["spec"]
    title, subtitle = esc(spec.get("title", "Diagram")), esc(spec.get("subtitle", ""))
    legend = spec.get("legend") or []
    legend_html = "".join(f'<span class="legend-item"><i style="background:{esc(item.get("color", "#64748b"))}"></i>{esc(item.get("label", ""))}</span>' for item in legend)
    number = f'<span class="figure-number">{esc(spec.get("number"))}</span>' if spec.get("number") else ""
    figure_meta = f'<p class="figure-meta"><b>泳道：</b>{esc(spec.get("figure_meta"))}</p>' if spec.get("figure_meta") else ""
    legacy_css = '.figure-number{display:inline-flex;width:36px;height:36px;border-radius:10px;background:#0f172a;color:#fff;align-items:center;justify-content:center;font-size:14px;font-weight:800;margin-right:12px}.figure-head{display:flex;align-items:flex-start}.figure-meta{font-size:11.5px;color:#64748b;margin:0 0 9px}' if spec.get("_legacy_swimlane") else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
body{{margin:0;padding:28px;background:#f4f7fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",sans-serif}}main{{max-width:1600px;margin:auto;background:#fff;border:1px solid #dfe6ef;border-radius:18px;padding:24px;box-shadow:0 10px 28px #182b4512}}h1{{margin:0;color:#10233f;font-size:26px}}.subtitle{{margin:6px 0 18px;color:#64748b}}.scroll{{overflow:auto;border:1px solid #e2e8f0;border-radius:12px;padding:8px;background:#fbfdff}}.actor-t{{font-size:13px;font-weight:700;fill:#172033}}.lifeline{{stroke:#94a3b8;stroke-width:1.4;stroke-dasharray:5 5}}.msg{{fill:none}}.lbl{{font-size:11px;fill:#475569}}.tag{{fill:#fff7ed;stroke:#fed7aa}}.tag-t{{font-size:10px;fill:#92400e}}.lane-title{{font-size:15px;font-weight:700;fill:#334155}}.lane-sub,.edge-label{{font-size:11px;fill:#64748b}}.node-title{{font-size:14px;font-weight:700;fill:#172033}}.decision-title{{font-size:13px;font-weight:700;fill:#92400e}}.node-sub{{font-size:10px;fill:#475569}}.decision-sub{{font-size:10px;fill:#92400e}}.node-footer{{font-size:9px;fill:#64748b}}.legend{{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 16px;color:#475569;font-size:12px}}.legend-item{{display:inline-flex;align-items:center;gap:6px}}.legend-item i{{width:10px;height:10px;border-radius:50%;display:inline-block}}{legacy_css}</style></head><body><main><div class="figure-head">{number}<div><h1>{title}</h1><p class="subtitle">{subtitle}</p></div></div>{figure_meta}{f'<div class="legend">{legend_html}</div>' if legend_html else ''}<div class="scroll">{svg(layout)}</div></main></body></html>'''


def element_count(spec: dict) -> int:
    """Diagram-bearing elements a spec asks for; zero means the figure would be blank."""
    if spec.get("type") == "sequence":
        return len(spec.get("participants", [])) + len(spec.get("messages", []))
    nodes = len(spec.get("nodes", [])) or sum(len(column.get("nodes", [])) for column in spec.get("columns", []))
    return nodes + len(spec.get("edges", []))


BROWSER_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge", "microsoft-edge", "microsoft-edge-stable", "brave-browser")
BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_browser() -> str | None:
    """Locate a Chromium-family browser for --png, on macOS, Linux, and Windows."""
    import shutil
    explicit = os.environ.get("CHROME_BIN") or os.environ.get("BROWSER_BIN")
    if explicit:
        return explicit if Path(explicit).exists() or shutil.which(explicit) else None
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for guess in BROWSER_PATHS:
        if Path(guess).exists():
            return guess
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and validate a semantic diagram JSON spec")
    parser.add_argument("spec", type=Path)
    parser.add_argument("-o", "--output", "--out", dest="output", type=Path)
    parser.add_argument("--png", type=Path, help="also write a PNG using headless Chrome")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()
    try:
        spec = load(args.spec)
        layout, errors = prepare(spec)
        issues = errors + check(layout)
        warnings = list(layout.get("quality_warnings", []))
        if spec.get("_legacy_extracted"):
            for warning in spec.get("_extraction_warnings", []):
                warnings.append(warning)
        empty = element_count(spec) == 0
        if empty:
            warnings.append("spec defines no diagram elements; the rendered figure is empty")
        if spec.get("_legacy_extracted") and spec.get("type") != "sequence":
            for node in layout["positions"].values():
                if node["kind"] == "decision":
                    outgoing = [edge for edge in spec.get("edges", []) if edge.get("from") == node["id"]]
                    if outgoing and any(not edge.get("label") for edge in outgoing):
                        warnings.append(f"legacy decision outcome labels unavailable: {node['id']}")
        if not args.quiet:
            if issues:
                print("validation: FAIL")
                print("\n".join(f"  - {issue}" for issue in sorted(set(issues))))
            else:
                print(f"validation: PASS ({len(spec.get('participants', []))} participants, {len(spec.get('messages', []))} messages)" if spec.get("type") == "sequence" else f"validation: PASS ({len(spec.get('nodes', []))} nodes, {len(spec.get('edges', []))} edges)")
            for warning in warnings:
                print(f"warning: {warning}")
        output = args.output or (args.png.with_suffix(".html") if args.png else None)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render(layout), encoding="utf-8")
            if not args.quiet:
                print(f"written: {output}")
        if args.png:
            if not output:
                raise ValueError("--png requires an output HTML path or an internally derived path")
            import shutil
            import subprocess
            chrome = find_browser()
            if not chrome:
                raise RuntimeError(
                    "no Chrome, Chromium, or Edge found for --png; "
                    "install one or set CHROME_BIN to the browser executable")
            args.png.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                            f"--screenshot={args.png}", f"--window-size={int(layout['width']) + 80},{int(layout['height']) + 200}",
                            output.resolve().as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not args.quiet:
                print(f"written: {args.png}")
        if empty:
            return 2
        return 1 if issues and args.check else 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
