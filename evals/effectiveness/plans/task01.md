# Director plan: Task 01

Acceptance: preserve every public validation rule and event-order tie rule. Return the exact invalid sentinel for malformed input or any cycle, including one in a disconnected component. Return all schedule fields for the empty graph.

Separate validation, acyclicity, and scheduling. Reject bool where an integer is required. Validate the top-level object and task/dependency containers before performing dictionary lookups or set operations; validate ID types before hashing them. Build the complete ID table first, then resolve dependencies so input order is immaterial. Validate duplicate dependency entries explicitly. Do not accidentally accept an unknown dependency or coerce strings to integers. Apply the public extra-key and size policies exactly.

Use Kahn's algorithm (or equivalent) to reject cycles before constructing a partial schedule. For scheduling, keep remaining dependency counts and reverse adjacency. Ready tasks use a min-heap by ID. Running tasks use a heap by finish time and ID. Fill every free slot from ready tasks. If running is nonempty, jump directly to its minimum finish time; remove ALL tasks finishing then, mark them finished, update all dependants, then refill slots. Do not start new tasks while still processing same-time completions. Record start order at actual dispatch, start and finish times in maps, and greatest finish time.

Review probes from public semantics: zero tasks; one lane; more lanes than tasks; dependency listed later; disconnected cycle; simultaneous releases that create competing ready IDs; validation of bool duration/workers and non-string dependencies. Do not use tests outside the public contract. Complexity should scale with tasks/edges and heap operations, not makespan.
