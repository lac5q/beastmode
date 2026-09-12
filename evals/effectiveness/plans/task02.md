# Director plan: Task 02

Acceptance: validate the entire graph before returning a schedule; compute the stated downstream critical length, then obey descending critical length and ascending ID at each dispatch event. The priority is fixed from the full DAG, not recomputed as remaining duration.

Validate object/container types and reject bool for numeric fields. Build all IDs before resolving dependencies, reject duplicates/unknown IDs/self-edges, and find a topological order to reject cycles anywhere. Follow the public policy on extra fields and bounds. Traverse topological order in reverse: critical[id] = duration[id] + max(critical[child] for direct dependants, default 0). A shared descendant contributes through max, never a sum.

Maintain indegrees for dispatch separately from those consumed by topological validation. Ready heap key is (-critical[id], id); running heap key is (finish_time, id). Dispatch until lanes are full. Jump to the next completion time, pop every task finishing then, and update all dependants before dispatching again. This avoids a same-time completion interleaving bug. Record start order, per-ID start/finish, makespan, and critical map, including the specified empty result.

Review probes: equal critical priorities resolved by ID; shorter task with longer downstream path outranking a long leaf; fan-out and reconverging paths; later-listed dependencies; simultaneous completions; invalid bool or cycle. The public specification outranks this plan if wording differs. Use event jumps rather than unit-time iteration.
