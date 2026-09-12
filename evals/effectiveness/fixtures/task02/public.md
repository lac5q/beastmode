# Task 02: critical-path build scheduler

Implement a pure Python `solve(payload)` function with JSON-compatible input and output.

The valid input is an object with integer `lanes` in `1..80` and a `tasks` array of at most 80 tasks. Each task has a unique non-empty string `id` of at most 40 Unicode characters, a positive integer `duration` in `1..100000`, and a `deps` array of distinct string IDs. Every dependency must occur in the array. Empty `tasks` is valid. Booleans do not count as integers. For a missing field, wrong type, duplicate ID or dependency, unknown dependency, self-dependency, cycle, or any other violation, return exactly `{"error":"invalid"}`. Unknown object keys are ignored.

Tasks run on `lanes` identical build lanes. Time is integral and begins at zero. A task is ready only when all dependencies have finished. For every ready task, first compute its critical length as its own duration plus the largest critical length among its direct dependants; a task with no dependant has critical length equal to its duration. At each time when tasks finish, finish all of them before starting work. At time zero do the same start step. When slots compete, choose ready tasks by descending critical length, then lexicographically ascending ID. Start as many as fit. Tasks that finish together release all their lanes together.

Return `order` (IDs in the exact order they started), `start` (each ID to its integer start time), `finish` (each ID to its integer finish time), `makespan` (the greatest finish time, or `0` for no tasks), and `critical` (each ID to its computed critical length). No extra keys are needed; object key order is irrelevant.
