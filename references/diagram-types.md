# Choosing a diagram type

Choose the smallest view that answers the reader's question.

| Type | Use when the reader needs to understand | Main elements |
| --- | --- | --- |
| Process flow | ordered actions and decisions | process nodes, decisions, outcomes |
| Swimlane | who or which boundary performs each step | lanes, process nodes, cross-lane edges |
| System map | systems and their relationships | actors, systems, external services, dependencies |
| Architecture | layers and deployable or logical boundaries | containers, components, boundaries |
| Data flow | movement and transformation of information | sources, transformations, stores, destinations |
| Lifecycle | states and allowed transitions | state nodes and labeled transitions |
| Sequence | messages exchanged over time | participants, ordered requests and responses |
| Overview | a compact map of several related areas | grouped nodes, links, short labels |

Use a lane only when responsibility or a system boundary is part of the explanation. Use a separate focused diagram when a view needs more than one main reading direction.

For a sequence diagram, keep one vertical time axis and make every message horizontal. Use response styling for return messages, annotations for short source-grounded notes, and split the view when labels or participants become crowded.
