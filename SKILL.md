---
name: diagram-production
description: Create and revise source-grounded business and technical diagrams as structured data, then render and validate them as HTML/SVG. Use for process flows, swimlanes, system maps, architecture views, data flows, lifecycles, sequences, and overview diagrams.
metadata:
  short-description: Generate validated diagrams from structured specs
---

# Diagram production

Use this skill when the user needs a diagram that must remain editable, reproducible, and consistent across revisions. The skill is domain-neutral: do not assume a company, product, workflow, brand, or internal system. It is the single entry point for process flows, swimlanes, system maps, architecture views, data flows, lifecycles, sequences, and overview diagrams. It fully replaces the former swimlane-only workflow, including its legacy spec and CLI compatibility.

## Source of truth

Keep diagram meaning in a JSON spec. Do not hand-edit generated SVG coordinates or the final HTML. A spec contains:

- type: process, swimlane, system-map, architecture, data-flow, lifecycle, or sequence;
- title and optional subtitle;
- lanes when the diagram has responsibility bands;
- nodes with stable id, visible text, semantic kind, and optional lane and column;
- edges with explicit from, to, optional label, and a meaning such as flow, request, response, return, or dependency;
- optional theme overrides that remain generic and accessible.

If the source material is ambiguous, mark the node or edge as uncertain in the visible note or spec metadata. Do not invent systems, statuses, roles, or integrations.

For type selection and density decisions, read [references/diagram-types.md](references/diagram-types.md) and [references/layout-rules.md](references/layout-rules.md). For a legacy HTML/SVG starting point, read [references/legacy-svg.md](references/legacy-svg.md).

## Workflow

1. Identify the reader's primary question and choose one diagram type.
2. Extract the semantic inventory before drawing: actors, systems, states, actions, data objects, boundaries, outcomes, and unresolved assumptions.
3. Present the proposed lanes, nodes, and edges as a short text list before rendering when the user is still deciding the business meaning.
4. Write or update the JSON spec. Use semantic IDs and columns; do not add pixel coordinates for a new diagram.
5. Render with `scripts/diagram.py`.
6. Run the same command with `--check`. Fix dangling edges, overlaps, lane overflow, connector crossings, decision branches, and text overflow before delivery.
7. Inspect the rendered HTML at the target viewport. Check clipping, reading order, connector endpoints, and branch meaning.
8. Deliver the generated artifact and retain the spec beside it for future edits.

## Existing HTML or SVG

When the starting point is a hand-authored or legacy diagram, extract it before changing it:

~~~bash
python3 scripts/extract_svg.py source.html --svg-index 0 -o extracted.json
python3 scripts/diagram.py extracted.json -o rebuilt.html --check
python3 scripts/verify_render.py source.html rebuilt.html --svg-index 0
# legacy selectors are accepted too:
python3 scripts/extract_svg.py source.html --fig 10 -o fig10.json
python3 scripts/extract_svg.py source.html --all -d specs/
~~~

Extraction preserves visible labels, their `label_at` coordinates, approximate lanes, node geometry, legacy `w/h` aliases, `_rhythm`, `figure_meta`, `number`, lane padding, and orthogonal routes. It cannot recover business meaning that is not present in the artwork, so review the extracted node and edge list before editing. Extracted specs carry `_legacy_extracted: true`; historical ambiguities such as an unlabeled decision are reported as warnings during `--check`. Use `--svg-index` when a document contains more than one SVG.

## Layout rules

- Use one primary reading direction per diagram.
- Use lanes only when responsibility or system boundary is part of the explanation.
- Keep a main path visually distinct from return, dependency, or external edges.
- Route branches through dedicated channels; never draw a return edge through a decision or another node.
- Split diagrams when the primary path is no longer readable. Prefer several focused diagrams over a dense poster.
- Use labels for the meaning of an edge, not for implementation commentary.
- Keep styles semantic: decisions use diamonds, systems use system styling, external boundaries use a distinct treatment, and notes stay outside the main path.

## Output

The renderer produces a self-contained HTML file with inline SVG and CSS. The HTML is the portable source for browser preview and can be embedded into a larger report. PNG export is optional and must not replace the JSON spec or HTML source.

Run:

~~~bash
python3 scripts/diagram.py examples/swimlane.json -o build/swimlane.html --check
python3 scripts/diagram.py examples/system-map.json -o build/system-map.html --check
python3 scripts/diagram.py examples/swimlane.json -o build/swimlane.html --png build/swimlane.png --check
~~~

`--png` is the only optional dependency: it drives a Chromium-family browser in headless mode. The renderer looks for `CHROME_BIN`, then `google-chrome`, `chromium`, `chrome`, `msedge`, or `brave-browser` on `PATH`, then the usual install paths on macOS, Linux, and Windows. When no browser is found it writes the HTML, skips the PNG, and exits 2 with a message naming `CHROME_BIN`. Everything else needs only Python 3.9+ and the standard library.

## Compatibility with legacy swimlane specs

The renderer accepts the former swimlane fields: `columns`, `w`/`h`, `x`/`y`, `shape`, `cls`, `meta_cls`, `tag_cls`, `meta_y`, `tag_y`, `pad_top`, `pad_bottom`, `_h_fixed`, `_viewbox`, `_rhythm`, `palette`, `labels`, `ext`, `dash`, `route`, and `label_at`. Existing fixed-coordinate specs keep their coordinates; new diagrams should continue to omit coordinates and use semantic columns.

The CLI also accepts the former aliases `--out`, `--png`, and `-q`. The verification helper accepts both `source.html rendered.html` and the legacy `source.html --spec spec.json --html rendered.html` form.

Read references/spec-format.md for the schema and references/quality-gates.md for the checks to apply before delivery.

## Boundaries

This skill does not provide company-specific process knowledge, logos, internal paths, private API names, or proprietary templates. Keep those in the user's project, outside the public skill. Do not copy private examples into examples/. Do not treat an extracted diagram as verified business truth; extraction is a starting point for review.

## Sequence diagrams

For interactions over time, use `type: sequence` with `participants`, `messages`, and optional `annotations`. Participants become top actor boxes with vertical lifelines. Messages are ordered by their list position, carry `from`, `to`, `label`, and an optional `kind` (`flow`, `request`, `response`, or `return`), and may preserve a reviewed legacy `label_at`. Run `--check` to catch overlapping participants, invalid message references, non-monotonic rows, endpoint drift, out-of-viewBox geometry, and annotation overflow. Existing actor/lifeline/message SVGs can be extracted with the same `extract_svg.py` workflow; malformed historical arrow polygons are reported as warnings rather than silently treated as business semantics.

A spec that defines no diagram elements is reported as a warning and exits with code 2 instead of passing silently. An annotation without coordinates is placed after its associated message row. The sequence checker rejects annotation boxes that cover participant boxes. When extraction recognizes no diagram elements, it writes `type: unknown`, records and prints an incomplete-extraction warning, and exits with code 2, so a source that uses only unclassified inline SVG is not mistaken for a successful reverse engineering result.
