# Diagram spec format

The renderer accepts JSON with a stable semantic model:

~~~json
{
  "type": "swimlane",
  "title": "Example approval flow",
  "subtitle": "A small, source-grounded flow",
  "lanes": [
    {"id": "people", "name": "People", "sub": "Actors", "style": "yc"},
    {"id": "platform", "name": "Platform", "sub": "System work", "style": "pf"}
  ],
  "nodes": [
    {"id": "submit", "lane": "people", "column": 0, "kind": "actor", "title": "Submit request", "sub": "Provide required data"},
    {"id": "check", "lane": "platform", "column": 1, "kind": "decision", "title": "Valid?", "sub": "Required fields"},
    {"id": "done", "lane": "platform", "column": 2, "kind": "state", "title": "Completed", "sub": "Record result"}
  ],
  "edges": [
    {"from": "submit", "to": "check", "kind": "flow"},
    {"from": "check", "to": "done", "label": "yes", "kind": "flow"},
    {"from": "check", "to": "submit", "label": "no", "kind": "return"}
  ]
}
~~~

column controls the reading order. The renderer computes coordinates from columns and lanes. Do not add x or y to a source spec.

Useful kind values are actor, process, decision, system, external, state, and note. Useful edge kinds are flow, return, request, response, dependency, and external.

Keep visible labels short. Put source, uncertainty, or implementation detail in a note outside the main path or in project-specific metadata.

## Fields

- `type` is descriptive metadata. Use `process`, `swimlane`, `system-map`, `architecture`, `data-flow`, `lifecycle`, `sequence`, or another project label.
- `lanes` is optional. A lane has `id`, visible `name`, optional `sub`, optional `style`, `fill`, and `stroke`.
- `nodes` is the preferred form. Each node needs a stable `id`, visible `title`, and optional `sub`, `meta`, `tag`, `kind`, `lane`, `column`, `width`, `height`, `fill`, and `stroke`.
- `columns` is accepted as a compact alternative for hand-authored specs. Each column has an optional `stage` and a `nodes` list; the renderer converts it to nodes with column numbers.
- `edges` need `from` and `to`. Optional `label`, `kind`, `color`, `route`, and `label_at` control meaning and presentation. Do not add `route` to new specs unless automatic routing cannot express a deliberate exception.
- `legend` is optional and contains `{label, color}` items for visible edge or node conventions.

The renderer computes positions. Coordinates from a legacy extraction are useful for comparison, but should be removed when starting a new layout so the automatic layout can respond to content changes.

## Legacy compatibility

Specs produced by the former swimlane renderer can be passed to `scripts/diagram.py` unchanged. In that form, `columns` supplies the reading order, `w`/`h` are accepted aliases for `width`/`height`, and a spec where every node has `x` and `y` enters fixed-coordinate mode. Fixed mode also honors `_viewbox`, lane `y`/`_h_fixed`, `pad_top`/`pad_bottom`, `_rhythm`, `palette`, node class fields, and explicit edge routes. Specs extracted from an existing artifact carry `_legacy_extracted: true`; this enables warning-level handling for semantics that cannot be recovered from pixels or SVG text alone.

## Sequence diagrams

A sequence spec uses participants and ordered messages instead of lanes and nodes:

~~~json
{
  "type": "sequence",
  "title": "Generic request sequence",
  "participants": [
    {"id": "caller", "title": "Caller", "cls": "hm"},
    {"id": "service", "title": "Service", "cls": "pf"}
  ],
  "messages": [
    {"from": "caller", "to": "service", "label": "Request", "kind": "flow"},
    {"from": "service", "to": "caller", "label": "Response", "kind": "response"}
  ],
  "annotations": [{"text": "A source-grounded note."}]
}
~~~

The renderer computes participant boxes, vertical lifelines, message rows, arrow direction, response styling, labels, and annotation boxes. New specs should omit coordinates. The optional `row_height`, `lifeline_top`, `lifeline_bottom`, `label_at`, `x`, `y`, `width`, and `height` fields are available when preserving a reviewed legacy artifact. `kind` values `flow`, `request`, `response`, and `return` are supported; response and return messages are dashed and point back to the sender.

Annotations without an explicit `y` are placed after their corresponding message row (the first annotation follows row 1). The checker rejects annotation boxes that overlap participant boxes, exceed the viewBox, or cannot contain their text.
