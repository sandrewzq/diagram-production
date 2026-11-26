# Legacy HTML/SVG workflow

Use the legacy workflow when the source diagram already exists as HTML or SVG and the goal is to revise it without losing its visible structure.

1. Run `scripts/extract_svg.py` and select the SVG with `--svg-index` if needed. Documents that label figures can use the compatible `--fig N`; use `--all -d specs/` to export every SVG.
2. Inspect the JSON. Rename unstable generated IDs, correct lane membership, and add missing edge labels only when the source supports them.
3. Render with `scripts/diagram.py --check`.
4. Run `scripts/verify_render.py` against the original when the change is intended to preserve structure.

The extractor recognizes common classes such as `lane`, `lane-title`, `lane-sub`, `node`, `node-title`, `node-sub`, `decision`, `edge`, and `arrow`. It stores edge label coordinates as `label_at` so a re-render does not recalculate historical labels. Extracted specs are marked `_legacy_extracted: true`; this keeps historical decision-label gaps as warnings instead of treating them as new-diagram defects. Class names vary across documents; when they do not match, treat the extracted result as partial and complete the semantic spec manually.

## Legacy sequence SVGs

Legacy layout is detected from geometry and retired class vocabulary, never from node class names: the old band inset was 12px (the current one is 16px), and old files also carry `lane-band` or `nd-title`/`nd-sub`/`nd-meta`/`nd-tag`. A diagram rendered by this skill therefore stays on the current layout unless it really was legacy.

The extractor recognizes `actor`, `actor-t`, `lifeline`, `msg`, `msg ret`, `lbl`, `tag`, and `tag-t`. It produces a `type: sequence` spec with participant geometry, ordered messages, response kinds, label coordinates, annotations, and `_legacy_sequence: true`. Arrowhead polygons are secondary evidence. If an old file contains a polygon outside the SVG viewBox, the extractor ignores it and records `_extraction_warnings`; valid message line endpoints remain authoritative.

If a source SVG has no recognized lanes, nodes, edges, or sequence elements, extraction still returns a reviewable spec but records `_extraction_warnings` and prints a warning. Treat a zero-element extraction as incomplete reverse engineering, not as a successful semantic conversion: the spec carries `type: unknown` and the command exits with code 2 while still writing the JSON, so a pipeline can stop on it and a human can still inspect the file.
