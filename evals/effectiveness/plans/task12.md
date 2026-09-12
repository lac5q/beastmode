# Director plan: Task 12

Acceptance: exact maximum-priority dependency-closed subset under both resource budgets. Break ties by lower total cpu+memory, then lexicographically smaller sorted IDs. Validate all graph constraints even when zero budgets force the empty solution.

Validate exact object field sets, all bounded non-bool integer values, unique bounded IDs, dependency array size/distinct strings, known references and no self-dependency. Build all IDs before resolving deps. Run a whole-graph cycle check before optimization; disconnected cycles are invalid too.

There are at most16 jobs, so enumerating all65536 masks is bounded and exact. Sort jobs by ID and precompute each direct dependency bitmask. For each subset, compute resource sums and priority (low-bit recurrence can reuse sums). Reject if either budget is exceeded. For every selected job require all its dependency bits in the same mask. Satisfying this for every selected job enforces transitive closure. Do not prune a mask merely because a smaller mask lacked a dependency: adding the missing job can make a superset valid. Compare feasible masks by highest priority, lower cpu+memory, then selected-ID tuple. Empty mask is a valid fallback with zero values.

Precomputing resource/priority arrays or checking budgets before closure keeps runtime bounded; a direct1-million-job-check enumeration is also plausible under the stated limits. Do not substitute greedy selection or independently optimize cpu and memory. Review probes: valuable job needs costly prerequisite, two parents sharing a dependency counted once, one budget binding, equal priority/resource sum with differing cpu/memory splits, ID tie, unknown dep/cycle, shuffled IDs, empty jobs and zero budget.
