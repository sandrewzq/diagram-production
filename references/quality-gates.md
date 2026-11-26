# Quality gates

Before delivering a diagram:

1. Every edge references an existing node.
2. Node IDs are unique and semantic.
3. Nodes do not overlap.
4. Nodes stay inside their lane.
5. No connector crosses an unrelated node.
6. Every decision has a visible outcome label and a path for each meaningful outcome. The checker flags unlabeled or pathless decisions; the author still confirms that the outcomes are semantically complete.
7. Return, response, dependency, and external edges use a distinct style and are explained in a legend or note.
8. Text fits the node; long explanations move to notes.
9. The primary path is readable in one direction.
10. The rendered artifact is inspected at the target viewport for clipping and ambiguous endpoints.

The `arrow-short-dogleg` check flags a sideways jog of up to 20 SVG units between parallel legs traveling in the same direction when the final leg is at most 30 units. It checks explicit routes as well as automatically routed edges. Legacy imports report it as a visual warning for review.

The bundled checker is intentionally conservative. A clean check is necessary but does not prove business semantics; review the source-grounded node and edge list as well. For a legacy diagram, use `extract_svg.py` followed by `verify_render.py` to catch structural drift.
