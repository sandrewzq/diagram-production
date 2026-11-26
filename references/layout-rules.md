# Layout rules

The renderer uses semantic columns and optional lanes. Keep the data model stable and let the renderer calculate coordinates.

- Assign a column to each step in the primary reading direction.
- Keep one primary path moving left to right. Use `return`, `response`, `dependency`, or `external` edge kinds for secondary relationships.
- Put nodes in the lane that owns the action. A system receiving a request belongs in its own lane when that boundary matters.
- Keep labels short enough to scan. Move rationale, source citations, and uncertainty to `meta`, `tag`, or a note outside the main path.
- Use a decision only when the outgoing alternatives matter. Label every outgoing decision edge.
- Use an explicit `route` only for a deliberate exception or a legacy reconstruction. New diagrams should rely on automatic routing.
- If a diagram has too many crossings or more than one dominant direction, split it into focused views.

The checker catches common geometric failures, but it cannot determine whether the business meaning is correct. Review the semantic inventory before treating a diagram as complete.
